"""Self-Improvement Lab — Chloe разбирает свои ошибки и предлагает, как стать лучше. Внедряет — только после «да».

Цикл: журнал → проблемы → предложение → проверка → «да» пользователя → внедрение (и отмена, если что).
1. Проблемы: неудачные шаги инструментов за неделю (отказы пользователя и срабатывания защиты — не ошибки),
   повторы одного и того же неудачного шага, поправки пользователя («не так», «неправильно»), падения в ~/.chloe/chloe.log.
2. Предложение пишет сильная модель: диагноз и одно из двух —
   урок (правило поведения в подсказке, кода не меняет) или правка кода (маленький патч).
3. Проверка патча: копия проекта (git worktree), патч, ВСЕ тесты — внутри песочницы (дом слоем, остальное только чтение,
   без сети). Не прошли — предложение не внедряется.
4. Внедрение: только после «да» голосом, отдельным коммитом в git (без отправки на GitHub); «отмени улучшение» — git revert.
Защитный слой (права, безопасность, песочница, ключи, подтверждения, сама лаборатория) патчами не меняется никогда:
это решает только человек. Патч, который удаляет или выключает тесты, тоже отклоняется.
Таблица lab_items в ~/.chloe/chloe.db.
"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time

from . import config
from .config import DATA, JOURNAL_FILE

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(PROJECT, ".venv", "bin", "python")
LAB_DIR = DATA / "lab"
TEST_TIMEOUT = 900
PROTECTED = {"chloe/permissions.py", "chloe/security.py", "chloe/sandbox.py", "chloe/secret.py", "chloe/config.py",
             "chloe/autostart.py", "chloe/lab.py", "chloe/tools/system.py", "chloe/tools/access.py", "chloe/tools/sec.py",
             "chloe/tools/improve.py", "start.sh", "run.py"}
PROTECTED_TESTS = {"tests/test_security.py", "tests/test_sandbox.py", "tests/test_permissions.py", "tests/test_keys_file.py",
                   "tests/test_lab.py", "tests/test_safety.py", "tests/test_secret.py", "tests/__init__.py"}
CORRECTION = re.compile(r"\b(не так|неправильно|не то|ошиблась|ошибся|зачем ты|я же сказал|не надо было|опять не)\b", re.I)
REFUSAL = ("Пользователь", "Отказано", "Не публикую", "Не озвучиваю", "Не делаю", "Не добавила", "Не удаляю", "Не отключаю",
           "Не блокирую", "Оставила", "Не одобряю")
STATUS = {"proposed": "предложено", "testing": "проверяется", "ready": "готово к внедрению", "failed": "не прошло проверку",
          "applied": "внедрено", "rejected": "отклонено", "undone": "отменено"}


class LabError(Exception):
    pass


def _key(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def normalize(error):
    """«Не найдено чата «Облако UZ»…» и «Не найдено чата «Onepress»…» — одна проблема."""
    e = re.sub(r"«[^»]*»|\"[^\"]*\"|'[^']*'", "«…»", error or "")
    e = re.sub(r"https?://\S+", "<адрес>", e)
    e = re.sub(r"\d+", "N", e)
    return e[:120].strip()


# --- 1. проблемы ---
def problems(days=7, now=None, db_path=None):
    """[{key, kind, title, tool, count, examples}] — от самых частых."""
    now = now or time.time()
    db = sqlite3.connect(str(db_path or JOURNAL_FILE), timeout=5)
    db.row_factory = sqlite3.Row
    since = now - days * 86400
    groups = {}

    def add(kind, title, tool, example, key_extra=""):
        k = _key(kind, tool, key_extra or title)
        g = groups.setdefault(k, {"key": k, "kind": kind, "title": title, "tool": tool, "count": 0, "examples": []})
        g["count"] += 1
        if len(g["examples"]) < 4 and example not in g["examples"]:
            g["examples"].append(example)

    try:
        for r in db.execute("SELECT ts, detail FROM events WHERE kind = 'tool' AND ok = 0 AND ts > ?", (since,)):
            try:
                d = json.loads(r["detail"] or "{}")
                d = json.loads(d) if isinstance(d, str) else d
            except ValueError:
                continue
            result = str(d.get("result", ""))
            if result.startswith(REFUSAL):
                continue
            tool = d.get("tool", "?")
            norm = normalize(result.replace("Ошибка: ", ""))
            add("tool", "{}: {}".format(tool, norm), tool,
                {"args": json.dumps(d.get("args", {}), ensure_ascii=False)[:300], "result": result[:300]}, norm)
        for r in db.execute("SELECT title FROM events WHERE kind = 'brain' AND ts > ? AND title LIKE 'Не повторяю%'", (since,)):
            add("loop", "Повтор неудачного шага", r["title"].split(": ")[-1], {"note": r["title"][:200]})
        rows = db.execute("SELECT id, ts, kind, title FROM events WHERE kind IN ('heard', 'said') AND ts > ? ORDER BY id", (since,)).fetchall()
        for i, r in enumerate(rows):
            if r["kind"] == "heard" and CORRECTION.search(r["title"] or ""):
                before = next((x["title"] for x in reversed(rows[max(0, i - 3):i]) if x["kind"] == "said"), "")
                add("correction", "Поправки пользователя", "", {"user": r["title"][:200], "chloe_before": (before or "")[:200]})
    except sqlite3.Error:
        pass
    finally:
        db.close()
    log = DATA / "chloe.log"
    if log.exists():
        try:
            text = log.read_text(encoding="utf-8", errors="replace")[-200000:]
            for m in re.finditer(r"Traceback \(most recent call last\):\n(?:.*\n){1,40}?(\w+(?:Error|Exception)[^\n]*)", text):
                tail = m.group(0).splitlines()
                where = next((l.strip() for l in reversed(tail) if l.strip().startswith('File "' + PROJECT)), "")
                add("crash", "Падение: " + normalize(m.group(1)), "", {"trace": "\n".join(tail[-8:])[:800], "where": where}, normalize(m.group(1)))
        except OSError:
            pass
    return sorted(groups.values(), key=lambda g: (-g["count"], g["kind"]))


# --- хранилище предложений ---
class Lab:
    def __init__(self, path=JOURNAL_FILE):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS lab_items (
            id INTEGER PRIMARY KEY, ts REAL NOT NULL, issue_key TEXT, title TEXT, kind TEXT, diagnosis TEXT, lesson TEXT,
            diff TEXT, files TEXT, status TEXT NOT NULL, test_result TEXT, applied_at REAL, commit_sha TEXT)""")
        self.db.commit()

    def add(self, issue, kind, diagnosis, lesson="", diff="", files=()):
        with self.lock:
            cur = self.db.execute("INSERT INTO lab_items (ts, issue_key, title, kind, diagnosis, lesson, diff, files, status) "
                                  "VALUES (?,?,?,?,?,?,?,?,?)", (time.time(), issue.get("key"), issue.get("title"), kind, diagnosis,
                                                                 lesson, diff, json.dumps(list(files)),
                                                                 "ready" if kind == "lesson" else "proposed"))
            self.db.commit()
            return cur.lastrowid

    def get(self, iid):
        with self.lock:
            r = self.db.execute("SELECT * FROM lab_items WHERE id = ?", (iid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["files"] = json.loads(d["files"] or "[]")
        return d

    def items(self, limit=20):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT id, ts, title, kind, status FROM lab_items ORDER BY id DESC LIMIT ?", (limit,))]

    def set(self, iid, **fields):
        with self.lock:
            self.db.execute("UPDATE lab_items SET {} WHERE id = ?".format(", ".join(k + " = ?" for k in fields)),
                            list(fields.values()) + [iid])
            self.db.commit()


# --- 2. предложение ---
def diff_files(diff):
    return sorted(set(re.findall(r"^\+\+\+ b/(\S+)", diff or "", re.M)) | set(re.findall(r"^--- a/(\S+)", diff or "", re.M)))


def check_diff(diff):
    """Причина отказа или None."""
    if not diff.strip():
        return "пустой патч"
    files = diff_files(diff)
    if not files:
        return "патч без файлов"
    for f in files:
        if f in PROTECTED or f in PROTECTED_TESTS:
            return "{} — защитный слой, его меняет только человек".format(f)
        if not (f.startswith("chloe/") or f.startswith("tests/")) or ".." in f:
            return "{} — вне кода Chloe".format(f)
        if f.startswith("chloe/ui/") and not f.endswith((".html", ".js", ".css")):
            return "{} — не тот файл".format(f)
    removed = "\n".join(l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    added = "\n".join(l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    if re.search(r"^\+\+\+ /dev/null", diff, re.M) and any(f.startswith("tests/") for f in files):
        return "патч удаляет тестовый файл"
    if re.search(r"def test_\w+", removed) and len(re.findall(r"def test_\w+", removed)) > len(re.findall(r"def test_\w+", added)):
        return "патч удаляет тесты"
    if re.search(r"(unittest\.skip|@skip|\.skipTest|assert True\b|pass\s*#\s*test)", added):
        return "патч выключает тесты"
    if re.search(r"(API_KEY|keys\.env|os\.environ\[[\"'][A-Z_]*KEY|subprocess.*shell=True.*input)", added):
        return "патч трогает ключи или запуск команд"
    return None


def source_hint(tool):
    """Код инструмента — чтобы модель правила то, что есть, а не придумывала."""
    if not tool:
        return ""
    try:
        import inspect

        from .tools import HANDLERS

        fn = HANDLERS.get(tool)
        if not fn:
            return ""
        file = inspect.getsourcefile(fn)
        path = os.path.relpath(file, PROJECT)
        with open(file, encoding="utf-8") as f:
            src = f.read()
        if len(src) > 14000:                                 # большой модуль — только сама функция
            src = inspect.getsource(fn)
        return "Файл {} (весь модуль, чтобы видеть и помощников инструмента):\n```python\n{}\n```\n".format(path, src[:14000])
    except (OSError, TypeError):
        return ""


PROMPT = """Ты — Self-Improvement Lab голосового ассистента Chloe (Python, Linux). Ниже повторяющаяся проблема из её журнала.
Разберись, в чём причина, и предложи ОДНО улучшение — самое простое, которое помогает.

Проблема: {title} (повторялась {count} раз за неделю, вид: {kind})
Примеры:
{examples}

{source}
Варианты ответа:
- "lesson": правило поведения для модели (одно-два предложения по-русски, конкретно: что делать в такой ситуации).
  Выбирай, если проблема в том, как модель пользуется инструментами (не тот инструмент, выдуманный адрес, неверные параметры),
  или в поведении (поправки пользователя).
- "code": маленькая правка кода (единый diff, пути относительно корня проекта: a/chloe/..., b/chloe/...; контекст 3 строки;
  строки контекста — ТОЧНО как в показанном коде). Выбирай, если ошибка в самом коде инструмента. Можно добавить тест в tests/.
  Нельзя трогать: {protected}. Нельзя удалять или выключать тесты, трогать ключи.
- "none": если это внешний сбой (нет сети, сайт недоступен, пользователь сам отказал) — исправлять нечего.

Ответь только JSON без пояснений вокруг:
{{"diagnosis": "причина простыми словами, 1–3 предложения", "kind": "lesson|code|none", "lesson": "текст урока или пусто",
  "diff": "единый diff или пусто", "summary": "что изменится для пользователя, одно предложение"}}"""


def ask_model(prompt, max_tokens=4000):
    """Сильная модель: Claude, если есть ключ; иначе DeepSeek; иначе Qwen."""
    if config.ANTHROPIC_KEY:
        import anthropic

        model = config.MIXED_STRONG or (config.MODEL_STRONG if (config.MODEL_STRONG or "").startswith("claude") else "claude-haiku-5-5")
        r = anthropic.Anthropic(timeout=180, max_retries=1).messages.create(
            model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if b.type == "text")
    from openai import OpenAI

    if config.DEEPSEEK_KEY:
        base, key, model = "https://api.deepseek.com", config.DEEPSEEK_KEY, "deepseek-chat"
    elif config.QWEN_KEY:
        from .thinking.openai_chat import qwen_base_url

        base, key, model = qwen_base_url(), config.QWEN_KEY, config.MODEL_STRONG or "qwen3.8-flash"
    else:
        raise LabError("нет ключа ни одной модели")
    r = OpenAI(base_url=base, api_key=key, timeout=180, max_retries=1).chat.completions.create(
        model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content or ""


def parse_answer(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise LabError("модель ответила не JSON")
    try:
        data = json.loads(m.group(0))
    except ValueError:
        raise LabError("модель ответила неполный JSON") from None
    kind = data.get("kind")
    if kind not in ("lesson", "code", "none"):
        raise LabError("непонятный вид предложения: {}".format(kind))
    return data


def propose(issue, lab, ask=ask_model):
    examples = "\n".join("- " + json.dumps(e, ensure_ascii=False)[:500] for e in issue["examples"])
    prompt = PROMPT.format(title=issue["title"], count=issue["count"], kind=issue["kind"], examples=examples,
                           source=source_hint(issue.get("tool")), protected=", ".join(sorted(PROTECTED)))
    data = parse_answer(ask(prompt))
    diagnosis = (data.get("diagnosis") or "").strip()
    if data["kind"] == "none":
        return lab.add(issue, "none", diagnosis or "исправлять нечего"), None
    if data["kind"] == "lesson":
        lesson = (data.get("lesson") or "").strip()
        if len(lesson) < 10:
            raise LabError("урок пустой")
        return lab.add(issue, "lesson", diagnosis, lesson=lesson[:500]), None
    diff = (data.get("diff") or "").strip() + "\n"
    problem = check_diff(diff)
    iid = lab.add(issue, "code", diagnosis + ("\nДля пользователя: " + data["summary"] if data.get("summary") else ""),
                  diff=diff, files=diff_files(diff))
    if problem:
        lab.set(iid, status="rejected", test_result="Отклонено проверкой: " + problem)
    return iid, problem


# --- 3. проверка ---
def _git(*args, cwd=None, timeout=60, input_text=None):
    return subprocess.run(["git", "-C", cwd or PROJECT] + list(args), capture_output=True, text=True, timeout=timeout, input=input_text)


def test_patch(diff, timeout=TEST_TIMEOUT):
    """(прошло?, отчёт). Копия проекта → патч → все тесты в песочнице. Настоящий проект не трогается."""
    from . import sandbox

    LAB_DIR.mkdir(parents=True, exist_ok=True)
    wt = str(LAB_DIR / "wt-{}".format(int(time.time() * 1000)))
    r = _git("worktree", "add", "--detach", wt, "HEAD")
    if r.returncode != 0:
        return False, "копия проекта не создалась: " + r.stderr.strip()[:200]
    try:
        r = _git("apply", "--check", "-", cwd=wt, input_text=diff)
        if r.returncode != 0:
            return False, "патч не ложится на код: " + r.stderr.strip()[:300]
        r = _git("apply", "-", cwd=wt, input_text=diff)
        if r.returncode != 0:
            return False, "патч не применился: " + r.stderr.strip()[:300]
        if not sandbox.available():
            return False, "песочница недоступна — без неё патчи не проверяю"
        # вывод тестов перемешан с печатью Chloe — итог ищем в файле, а не в хвосте
        t = sandbox.try_command("{} -m unittest discover -s tests -t . < /dev/null > /tmp/lab.out 2>&1; "
                                "grep -E '^(Ran |OK|FAILED|FAIL:|ERROR:)' /tmp/lab.out | tail -40".format(PYTHON), cwd=wt, timeout=timeout)
        out = t.get("output", "")
        if t.get("timeout"):
            return False, "тесты не уложились в {} минут".format(timeout // 60)
        ran = re.search(r"Ran (\d+) tests", out)
        ok = bool(ran) and re.search(r"^OK", out, re.M) is not None
        return ok, ("тесты прошли: {} шт.".format(ran.group(1)) if ok else "тесты не прошли:\n" + out[-1200:])
    finally:
        _git("worktree", "remove", "--force", wt)
        _git("worktree", "prune")


# --- 4. внедрение и отмена ---
def apply(item):
    """Урок — в подсказку; патч — в проект отдельным коммитом. Возвращает текст результата."""
    if item["kind"] == "lesson":
        from . import learning

        learning.learn_lesson(item["lesson"])
        return "урок записан — он уже в подсказке"
    if item["kind"] != "code" or item["status"] != "ready":
        raise LabError("внедрять можно только проверенный патч")
    problem = check_diff(item["diff"])
    if problem:
        raise LabError(problem)
    dirty = _git("status", "--porcelain", "--", *item["files"]).stdout.strip()
    if dirty:
        raise LabError("в этих файлах есть несохранённые изменения — сначала их нужно закоммитить")
    r = _git("apply", "--check", "-", input_text=item["diff"])
    if r.returncode != 0:
        raise LabError("код успел измениться, патч больше не ложится — предложу заново")
    _git("apply", "-", input_text=item["diff"])
    _git("add", "--", *item["files"])
    msg = "Self-Improvement Lab #{}: {}\n\n{}\n\nПроверено: {}".format(item["id"], item["title"][:80], item["diagnosis"][:600],
                                                                       item["test_result"] or "")
    r = _git("commit", "-q", "-m", msg, "--", *item["files"])
    if r.returncode != 0:
        _git("checkout", "--", *item["files"])
        raise LabError("коммит не прошёл: " + r.stderr.strip()[:200])
    return _git("rev-parse", "--short", "HEAD").stdout.strip()


def undo(item):
    if item["kind"] == "lesson":
        from . import learning

        want = re.sub(r"\s+", " ", item["lesson"]).strip()
        for i, x in enumerate(learning.lessons(), 1):
            if (x.get("text") if isinstance(x, dict) else x) == want:
                learning.forget_lesson(i)
                return "урок убран"
        return "урока уже нет"
    if not item.get("commit_sha"):
        raise LabError("нечего отменять")
    r = _git("revert", "--no-edit", item["commit_sha"])
    if r.returncode != 0:
        _git("revert", "--abort")
        raise LabError("отмена не прошла (код после этого менялся): " + r.stderr.strip()[:200])
    return _git("rev-parse", "--short", "HEAD").stdout.strip()


lab = Lab()
