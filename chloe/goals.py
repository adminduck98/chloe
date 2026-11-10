"""Goal System — большая цель → этапы → шаги: весь путь к цели виден целиком.

«Хочу запустить бизнес Smart Home» → цель (зачем, срок, проект) → этапы (исследование, оборудование, демо-стенд,
бизнес-модель, запуск) → шаги в каждом этапе. Прогресс считается по сделанным шагам; «что дальше по цели?» —
первый несделанный шаг первого незакрытого этапа. Шаг можно связать с задачей проекта: отметили задачу — шаг тоже готов.
Разбивку на этапы предлагает мозг Chloe словами, записывает — после согласия пользователя.
Таблицы goals и goal_steps в ~/.chloe/chloe.db; цели видны в «Связях» (граф и история) и в «Действиях» (сроки).
"""
import datetime
import sqlite3
import threading
import time

from .config import JOURNAL_FILE

STATUS = {"active": "в работе", "paused": "на паузе", "done": "достигнута", "dropped": "отменена"}
STEP = {"todo": "сделать", "doing": "в работе", "done": "готово"}
STALE_DAYS = 14


class GoalError(Exception):
    pass


def parse_date(text):
    t = (text or "").strip()
    if not t:
        return None
    try:
        return datetime.date.fromisoformat(t).isoformat()
    except ValueError:
        raise GoalError("срок — дата вида 2026-12-31") from None


class Goals:
    def __init__(self, path=JOURNAL_FILE):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, why TEXT, project TEXT, deadline TEXT, status TEXT NOT NULL DEFAULT 'active',
            created REAL, updated REAL, done_at REAL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS goal_steps (
            id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL, parent_id INTEGER, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo',
            pos INTEGER NOT NULL DEFAULT 0, task_id INTEGER, created REAL, done_at REAL)""")
        self.db.commit()

    # --- создание ---
    def add(self, title, why="", project=None, deadline=None, stages=()):
        title = (title or "").strip()
        if len(title) < 3:
            raise GoalError("нужно название цели")
        now = time.time()
        with self.lock:
            gid = self.db.execute("INSERT INTO goals (title, why, project, deadline, created, updated) VALUES (?,?,?,?,?,?)",
                                  (title[:200], (why or "").strip()[:600], (project or "").strip() or None, parse_date(deadline),
                                   now, now)).lastrowid
            for i, st in enumerate(stages or []):
                if isinstance(st, str):
                    st = {"title": st}
                sid = self._insert(gid, None, st.get("title"), i)
                for j, step in enumerate(st.get("steps") or []):
                    self._insert(gid, sid, step if isinstance(step, str) else step.get("title"), j)
            self.db.commit()
        return self.get(gid)

    def _insert(self, gid, parent, title, pos):
        title = (title or "").strip()
        if not title:
            raise GoalError("пустой этап или шаг")
        return self.db.execute("INSERT INTO goal_steps (goal_id, parent_id, title, pos, created) VALUES (?,?,?,?,?)",
                               (gid, parent, title[:200], pos, time.time())).lastrowid

    def add_step(self, gid, title, stage_id=None):
        with self.lock:
            if not self.get(gid):
                raise GoalError("нет такой цели")
            if stage_id is not None:
                st = self.db.execute("SELECT * FROM goal_steps WHERE id = ? AND goal_id = ? AND parent_id IS NULL", (stage_id, gid)).fetchone()
                if not st:
                    raise GoalError("нет такого этапа у этой цели")
            pos = self.db.execute("SELECT COALESCE(MAX(pos) + 1, 0) FROM goal_steps WHERE goal_id = ? AND parent_id IS ?",
                                  (gid, stage_id)).fetchone()[0]
            sid = self._insert(gid, stage_id, title, pos)
            self._touch(gid)
            self.db.commit()
            return sid

    # --- чтение ---
    def get(self, gid):
        with self.lock:
            g = self.db.execute("SELECT * FROM goals WHERE id = ?", (gid,)).fetchone()
            if not g:
                return None
            rows = [dict(r) for r in self.db.execute("SELECT * FROM goal_steps WHERE goal_id = ? ORDER BY pos, id", (gid,))]
        g = dict(g)
        stages = [dict(r, steps=[s for s in rows if s["parent_id"] == r["id"]]) for r in rows if r["parent_id"] is None]
        for st in stages:
            if st["steps"]:                                     # этап с шагами — готов, когда готовы все шаги
                st["done_n"], st["total_n"] = sum(s["status"] == "done" for s in st["steps"]), len(st["steps"])
            else:
                st["done_n"], st["total_n"] = int(st["status"] == "done"), 1
        g["stages"] = stages
        g["done_n"] = sum(st["done_n"] for st in stages)
        g["total_n"] = sum(st["total_n"] for st in stages)
        g["progress"] = round(100 * g["done_n"] / g["total_n"]) if g["total_n"] else 0
        g["next"] = self.next_step(g)
        return g

    def all(self, include_closed=False):
        with self.lock:
            ids = [r[0] for r in self.db.execute("SELECT id FROM goals" + ("" if include_closed else " WHERE status IN ('active','paused')")
                                                 + " ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id")]
        return [self.get(i) for i in ids]

    @staticmethod
    def next_step(g):
        for st in g["stages"]:
            if st["steps"]:
                for s in st["steps"]:
                    if s["status"] != "done":
                        return {"stage": st["title"], "step": s["title"], "id": s["id"]}
            elif st["status"] != "done":
                return {"stage": st["title"], "step": st["title"], "id": st["id"]}
        return None

    def find(self, text):
        t = str(text or "").strip()
        if t.isdigit():
            g = self.get(int(t))
            return [g] if g else []
        low = t.lower().replace("ё", "е")
        return [g for g in self.all(True) if low and low in g["title"].lower().replace("ё", "е")]

    def step(self, sid):
        with self.lock:
            r = self.db.execute("SELECT * FROM goal_steps WHERE id = ?", (sid,)).fetchone()
        return dict(r) if r else None

    def find_step(self, gid, text):
        g = self.get(gid)
        if not g:
            return []
        t = str(text or "").strip()
        every = [s for st in g["stages"] for s in [st] + st["steps"]]
        if t.isdigit():
            return [s for s in every if s["id"] == int(t)]
        low = t.lower().replace("ё", "е")
        return [s for s in every if low and low in s["title"].lower().replace("ё", "е")]

    # --- изменения ---
    def _touch(self, gid):
        self.db.execute("UPDATE goals SET updated = ? WHERE id = ?", (time.time(), gid))

    def set_step(self, sid, status):
        if status not in STEP:
            raise GoalError("статус шага: todo, doing, done")
        s = self.step(sid)
        if not s:
            raise GoalError("нет такого шага")
        with self.lock:
            self.db.execute("UPDATE goal_steps SET status = ?, done_at = ? WHERE id = ?",
                            (status, time.time() if status == "done" else None, sid))
            if s["parent_id"] is None and status == "done":   # этап целиком готов — и его шаги
                self.db.execute("UPDATE goal_steps SET status = 'done', done_at = COALESCE(done_at, ?) WHERE parent_id = ?",
                                (time.time(), sid))
            self._touch(s["goal_id"])
            self.db.commit()
        g = self.get(s["goal_id"])
        if g["total_n"] and g["done_n"] == g["total_n"] and g["status"] == "active":
            self.set_status(g["id"], "done")
            g = self.get(g["id"])
        return g

    def set_status(self, gid, status):
        if status not in STATUS:
            raise GoalError("статус цели: active, paused, done, dropped")
        with self.lock:
            self.db.execute("UPDATE goals SET status = ?, updated = ?, done_at = ? WHERE id = ?",
                            (status, time.time(), time.time() if status == "done" else None, gid))
            self.db.commit()
        return self.get(gid)

    def edit(self, gid, **fields):
        sets = {}
        for k in ("title", "why", "project"):
            if fields.get(k) is not None:
                sets[k] = str(fields[k]).strip()
        if fields.get("deadline") is not None:
            sets["deadline"] = parse_date(fields["deadline"])
        if not sets:
            return self.get(gid)
        with self.lock:
            self.db.execute("UPDATE goals SET {}, updated = ? WHERE id = ?".format(", ".join(k + " = ?" for k in sets)),
                            list(sets.values()) + [time.time(), gid])
            self.db.commit()
        return self.get(gid)

    def link_task(self, sid, task_id):
        with self.lock:
            self.db.execute("UPDATE goal_steps SET task_id = ? WHERE id = ?", (task_id, sid))
            self.db.commit()

    def sync_tasks(self):
        """Шаги, связанные с задачами проекта: задача сделана — шаг тоже. Возвращает, сколько шагов отмечено."""
        n = 0
        try:
            from .project_memory import project_memory as pm
        except Exception:
            return 0
        with self.lock:
            linked = [dict(r) for r in self.db.execute("SELECT * FROM goal_steps WHERE task_id IS NOT NULL AND status != 'done'")]
        for s in linked:
            t = pm.task(s["task_id"])
            if t and t["status"] == "done":
                self.set_step(s["id"], "done")
                n += 1
        return n

    def delete(self, gid):
        with self.lock:
            self.db.execute("DELETE FROM goal_steps WHERE goal_id = ?", (gid,))
            n = self.db.execute("DELETE FROM goals WHERE id = ?", (gid,)).rowcount
            self.db.commit()
        return n > 0

    def attention(self, now=None):
        """Что стоит заметить: сроки в ближайшую неделю, просроченные, давно без движения."""
        now = now or time.time()
        today = datetime.date.fromtimestamp(now)
        out = []
        for g in self.all():
            if g["status"] != "active":
                continue
            if g["deadline"]:
                left = (datetime.date.fromisoformat(g["deadline"]) - today).days
                if left < 0:
                    out.append({"goal": g, "why": "срок прошёл {} дн. назад, готово {}%".format(-left, g["progress"])})
                elif left <= 7:
                    out.append({"goal": g, "why": "до срока {} дн., готово {}%".format(left, g["progress"])})
            if now - (g["updated"] or g["created"]) > STALE_DAYS * 86400:
                out.append({"goal": g, "why": "без движения {} дн.".format(int((now - (g["updated"] or g["created"])) // 86400))})
        return out


goals = Goals()
