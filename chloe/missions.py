"""Задания — большая работа из нескольких шагов, которая не теряется при перезапуске.

«Подготовь проект к запуску» → план из шагов (проверить проект, найти ошибки, запустить тесты, …) → пользователь
соглашается → шаги идут по одному. Каждый шаг становится обычной просьбой к Chloe в её главном цикле (как у автоматизаций):
тот же мозг, те же инструменты, карта прав, вопросы «да/нет», журнал. Отдельного «исполнителя в обход» нет.

Шаг заканчивается отчётом мозга (mission report): готово / не вышло / нужен пользователь. Мозг забыл отчитаться —
шаг считается сделанным, итогом становится её ответ. «Нужен пользователь» — задание ждёт, Chloe задаёт вопрос;
ответ — «продолжи задание: …». Неудача — задание останавливается и ждёт решения: повторить, пропустить шаг, отменить.

Состояния задания: planned (план ещё не одобрен), running, waiting (ждёт пользователя), blocked (шаг не вышел),
paused (прервано перезапуском — само не продолжается, только по слову), done, cancelled.
Безопасный режим ставит задания на паузу. Одновременно идёт одно задание.
Таблицы missions и mission_steps в ~/.chloe/chloe.db.
"""
import sqlite3
import threading
import time

from .config import JOURNAL_FILE

STATUS = {"planned": "план ждёт согласия", "running": "идёт", "waiting": "ждёт вашего ответа", "blocked": "шаг не вышел",
          "paused": "прервано перезапуском", "done": "готово", "cancelled": "отменено"}
STEP = {"todo": "впереди", "running": "делается", "done": "готово", "failed": "не вышло", "skipped": "пропущен"}
OPEN = ("planned", "running", "waiting", "blocked", "paused")
MAX_STEPS = 10
POLL = 5                 # секунд между проверками: можно ли дать следующий шаг
QUIET_AFTER = 4          # секунд тишины после шага, прежде чем считать его законченным без отчёта


class MissionError(Exception):
    pass


class Missions:
    def __init__(self, path=JOURNAL_FILE):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS missions (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, request TEXT, status TEXT NOT NULL, question TEXT, answer TEXT,
            created REAL, updated REAL, finished REAL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS mission_steps (
            id INTEGER PRIMARY KEY, mission_id INTEGER NOT NULL, pos INTEGER NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'todo', result TEXT, started REAL, finished REAL)""")
        self.db.commit()

    # --- создание и чтение ---
    def create(self, title, steps, request=""):
        title = (title or "").strip()
        steps = [str(s).strip() for s in steps or [] if str(s).strip()]
        if len(title) < 3:
            raise MissionError("нужно название задания")
        if not 2 <= len(steps) <= MAX_STEPS:
            raise MissionError("в плане должно быть от 2 до {} шагов".format(MAX_STEPS))
        now = time.time()
        with self.lock:
            mid = self.db.execute("INSERT INTO missions (title, request, status, created, updated) VALUES (?,?,?,?,?)",
                                  (title[:200], (request or "")[:2000], "planned", now, now)).lastrowid
            for i, s in enumerate(steps):
                self.db.execute("INSERT INTO mission_steps (mission_id, pos, title) VALUES (?,?,?)", (mid, i, s[:300]))
            self.db.commit()
        return self.get(mid)

    def get(self, mid):
        with self.lock:
            m = self.db.execute("SELECT * FROM missions WHERE id = ?", (mid,)).fetchone()
            if not m:
                return None
            steps = [dict(r) for r in self.db.execute("SELECT * FROM mission_steps WHERE mission_id = ? ORDER BY pos", (mid,))]
        m = dict(m)
        m["steps"] = steps
        m["done_n"] = sum(s["status"] in ("done", "skipped") for s in steps)
        m["current"] = next((s for s in steps if s["status"] in ("running", "failed", "todo")), None)
        return m

    def all(self, include_closed=False, limit=20):
        with self.lock:
            q = "SELECT id FROM missions" + ("" if include_closed else " WHERE status IN ({})".format(",".join("?" * len(OPEN))))
            rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", (() if include_closed else OPEN) + (limit,)).fetchall()
        return [self.get(r[0]) for r in rows]

    def active(self):
        """Задание, которое сейчас идёт (одно)."""
        return next((m for m in self.all() if m["status"] == "running"), None)

    def find(self, text=None):
        """По номеру, по словам названия или — без слов — последнее незаконченное."""
        t = str(text or "").strip()
        if t.isdigit():
            return self.get(int(t))
        items = self.all()
        if t:
            low = t.lower().replace("ё", "е")
            items = [m for m in items if low in m["title"].lower().replace("ё", "е")]
        return items[0] if items else None

    # --- изменения ---
    def _set(self, mid, **fields):
        fields["updated"] = time.time()
        if fields.get("status") in ("done", "cancelled"):
            fields["finished"] = time.time()
        with self.lock:
            self.db.execute("UPDATE missions SET {} WHERE id = ?".format(", ".join(k + " = ?" for k in fields)),
                            list(fields.values()) + [mid])
            self.db.commit()

    def _step(self, sid, **fields):
        with self.lock:
            self.db.execute("UPDATE mission_steps SET {} WHERE id = ?".format(", ".join(k + " = ?" for k in fields)),
                            list(fields.values()) + [sid])
            self.db.commit()

    def approve(self, mid):
        m = self.get(mid)
        if not m or m["status"] != "planned":
            raise MissionError("нет плана, который ждёт согласия")
        if self.active():
            raise MissionError("уже идёт другое задание — сначала его закончим или поставим на паузу")
        self._set(mid, status="running")
        return self.get(mid)

    def begin_step(self, m):
        """Следующий шаг → «делается». Возвращает шаг или None, если шагов не осталось (задание готово)."""
        step = next((s for s in m["steps"] if s["status"] == "todo"), None)
        if step is None:
            self._set(m["id"], status="done")
            return None
        self._step(step["id"], status="running", started=time.time())
        return dict(step, status="running")

    def report(self, mid, outcome, result="", question=""):
        """Отчёт мозга о текущем шаге: done / failed / need_user."""
        m = self.get(mid)
        if not m or m["status"] not in ("running",):
            raise MissionError("это задание сейчас не выполняется")
        step = next((s for s in m["steps"] if s["status"] == "running"), None)
        if step is None:
            raise MissionError("нет шага в работе")
        result = (result or "").strip()[:2000]
        if outcome == "done":
            self._step(step["id"], status="done", result=result or "сделано", finished=time.time())
            if all(s["status"] in ("done", "skipped") or s["id"] == step["id"] for s in m["steps"]):
                self._set(mid, status="done")
        elif outcome == "failed":
            self._step(step["id"], status="failed", result=result or "не вышло", finished=time.time())
            self._set(mid, status="blocked")
        elif outcome == "need_user":
            self._step(step["id"], status="todo", result=result or None)          # шаг повторится с ответом пользователя
            self._set(mid, status="waiting", question=(question or result or "нужен ваш ответ")[:500])
        else:
            raise MissionError("outcome: done, failed или need_user")
        return self.get(mid)

    def resume(self, mid, answer=""):
        """Продолжить: после вопроса (с ответом), после неудачи (повторить шаг) или после перезапуска."""
        m = self.get(mid)
        if not m or m["status"] not in ("waiting", "blocked", "paused", "planned"):
            raise MissionError("это задание не на паузе")
        other = self.active()
        if other and other["id"] != mid:
            raise MissionError("уже идёт задание №{} — сначала его".format(other["id"]))
        for s in m["steps"]:
            if s["status"] in ("failed", "running"):
                self._step(s["id"], status="todo")
        fields = {"status": "running", "question": None}
        if answer.strip():
            fields["answer"] = ((m["answer"] + "\n") if m["answer"] else "") + answer.strip()[:1000]
        self._set(mid, **fields)
        return self.get(mid)

    def skip(self, mid):
        m = self.get(mid)
        if not m or m["status"] not in ("blocked", "waiting", "paused"):
            raise MissionError("пропустить шаг можно, когда задание остановилось")
        cur = m["current"]
        if cur:
            self._step(cur["id"], status="skipped", finished=time.time())
        return self.resume(mid)

    def cancel(self, mid):
        m = self.get(mid)
        if not m or m["status"] not in OPEN:
            raise MissionError("нет такого незаконченного задания")
        self._set(mid, status="cancelled")
        return self.get(mid)

    def recover(self):
        """После перезапуска: «шёл» → «прервано». Само не продолжается — только по слову пользователя."""
        n = 0
        for m in self.all():
            if m["status"] == "running":
                for s in m["steps"]:
                    if s["status"] == "running":
                        self._step(s["id"], status="todo")
                self._set(m["id"], status="paused")
                n += 1
        return n


missions = Missions()


# --- тексты ---
def plan_text(m):
    return "; ".join("{}) {}".format(i + 1, s["title"]) for i, s in enumerate(m["steps"]))


def describe(m, full=False):
    head = "Задание №{} «{}» — {}, сделано {} из {}.".format(m["id"], m["title"], STATUS.get(m["status"], m["status"]),
                                                          m["done_n"], len(m["steps"]))
    if m["status"] == "waiting" and m["question"]:
        head += " Вопрос: " + m["question"]
    if not full:
        return head
    lines = [head]
    for i, s in enumerate(m["steps"], 1):
        lines.append("{}. [{}] {}{}".format(i, STEP.get(s["status"], s["status"]), s["title"],
                                           " — " + s["result"][:300] if s["result"] else ""))
    return "\n".join(lines)


def step_request(m, step):
    """Шаг → просьба к Chloe в главном цикле."""
    n = next(i for i, s in enumerate(m["steps"], 1) if s["id"] == step["id"])
    done = [s for s in m["steps"] if s["status"] in ("done", "skipped") and s["result"]]
    parts = ["Задание №{} «{}», шаг {} из {}: {}.".format(m["id"], m["title"], n, len(m["steps"]), step["title"])]
    if m["request"]:
        parts.append("Исходная просьба пользователя: " + m["request"][:500])
    if done:
        parts.append("Что уже сделано: " + " | ".join("{}: {}".format(s["title"][:60], s["result"][:300]) for s in done[-4:]))
    if step.get("result"):
        parts.append("В прошлый раз на этом шаге: " + step["result"][:300])
    if m["answer"]:
        parts.append("Ответ пользователя: " + m["answer"][-600:])
    parts.append("Сделай только этот шаг, по-настоящему, своими инструментами. Потом обязательно вызови "
                 "mission(action=report, id={}, outcome=done|failed|need_user, result=что сделано и что нашлось, "
                 "question=что спросить у пользователя — только для need_user). Скажи итог шага в одну-две фразы.".format(m["id"]))
    return " ".join(parts)


# --- исполнитель ---
_feed = {"step": None, "pushed": 0.0}


def tick(now=None, say=None):
    """Одна проверка: если Chloe свободна — закрыть прошлый шаг (если мозг забыл отчитаться) и дать следующий."""
    from .settings import settings
    from .signals import Typed, busy, commands
    from .voice import voice

    now = now or time.time()
    if settings.get("safe_mode"):
        return None
    m = missions.active()
    if not m:
        _feed["step"] = None
        return None
    idle = not (busy.is_set() or voice.saying or voice.awaiting or commands.qsize() or getattr(voice, "recognizing", False)
                or now - getattr(voice, "last_loud", 0) < QUIET_AFTER)          # пользователь говорит — не перебиваем
    if not idle:
        _feed["pushed"] = max(_feed["pushed"], now)            # пока она работает — отсчёт тишины заново
        return None
    running = next((s for s in m["steps"] if s["status"] == "running"), None)
    if running:
        if now - _feed["pushed"] < QUIET_AFTER:
            return None
        # шаг прошёл, а отчёта нет: итог — её последний ответ
        missions.report(m["id"], "done", (getattr(voice, "last_said", "") or "сделано (без отчёта)")[:1000])
        m = missions.get(m["id"])
        if m["status"] != "running":
            return finish(m, say)
    step = missions.begin_step(m)
    if step is None:
        return finish(missions.get(m["id"]), say)
    _feed.update(step=step["id"], pushed=now)
    print("[задание] №{} шаг: {}".format(m["id"], step["title"][:80]))
    commands.put(Typed(step_request(missions.get(m["id"]), step), "local"))
    return step


def finish(m, say=None):
    if m and m["status"] == "done":
        text = "Задание «{}» готово: все {} шагов сделаны.".format(m["title"], len(m["steps"]))
        try:
            from .journal import journal

            journal.add("brain", "Задания", text, {"mission": m["id"]})
        except Exception:
            pass
        if say:
            say(text + " Подробности — «покажи задание {}».".format(m["id"]))
    return None


def runner(say, stop=None):
    while not (stop and stop.is_set()):
        try:
            tick(say=say)
        except Exception as e:
            print("[задания: {}]".format(str(e)[:100]))
        (stop.wait(POLL) if stop else time.sleep(POLL))


def start(say):
    n = missions.recover()
    if n:
        print("[задания: прервано перезапуском — {}; продолжаются по слову «продолжи задание»]".format(n))
    threading.Thread(target=runner, args=(say,), daemon=True, name="missions").start()
