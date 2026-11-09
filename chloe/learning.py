"""Обучение словами: свои навыки, сценарии и уроки.

- «Запомни, как это делается» — то, что Хлоя только что сделала, становится её навыком (~/.chloe/skills/<имя>/SKILL.md):
  в следующий раз — сразу по шагам, без поиска и лишних скриншотов.
- «Когда я говорю „работаем“ — открой…» — сценарий: навык со словами-триггерами. Сказали слово — он выполняется.
- «Неправильно, надо было так» / «впредь делай так» — урок: правило в каждой подсказке, пока его не забудут.

Выученные навыки — обычные SKILL.md: их можно открыть, поправить или удалить папку.
"""
import re
import time

from . import skillbook
from .journal import journal
from .settings import settings

MAX_LESSONS = 40
SKIP_TOOLS = {"save_skill", "learn_lesson", "forget_lesson", "learned_list", "use_skill", "read_skill_file",
              "conversation_log", "brain_usage"}


def norm(text):
    return re.sub(r"[^\w ]+", " ", str(text or "").lower().replace("ё", "е")).split()


def slug(name):
    s = re.sub(r"[^\w-]+", "-", str(name).strip().lower()).strip("-")
    return s[:60] or "навык"


def previous_task_steps(limit=25):
    """Шаги прошлой просьбы (той, что была до «запомни, как это делается»): что сделано и с какими параметрами."""
    with journal.lock:
        asks = journal.db.execute("SELECT id, title FROM events WHERE kind = 'heard' ORDER BY id DESC LIMIT 2").fetchall()
    if len(asks) < 2:
        return None, []
    ask = asks[1]
    with journal.lock:
        rows = journal.db.execute("SELECT kind, title, detail, ok FROM events WHERE task = ? AND kind = 'tool' ORDER BY id",
                                  (ask["id"],)).fetchall()
    steps = []
    for r in rows:
        tool = r["title"].split(":", 1)[0]
        if tool in SKIP_TOOLS:
            continue
        steps.append("{}{}".format(r["title"][:200], "" if r["ok"] else " (не сработало)"))
    return ask["title"], steps[:limit]


def save_skill(name, when, steps, triggers=None, from_last_task=True):
    """Пишет навык в ~/.chloe/skills/<имя>/SKILL.md (тот же имя — обновляет). Возвращает путь."""
    triggers = [t.strip() for t in (triggers or []) if str(t).strip()]
    lines = ["---", "name: " + slug(name), "description: " + re.sub(r"\s+", " ", str(when)).strip()[:300]]
    if triggers:
        lines.append("triggers: [{}]".format(", ".join('"{}"'.format(t.replace('"', "'")) for t in triggers)))
    lines += ["learned: true", "---", "", "# " + str(name).strip(), "",
              "Выучено со слов пользователя {}. Делай по шагам, без лишних скриншотов; если шаг не сработал "
              "(кнопка в другом месте, окно другое) — посмотри скриншотом, сделай и обнови навык (save_skill).".format(
                  time.strftime("%d.%m.%Y")), "", "## Шаги", str(steps).strip()]
    if from_last_task:
        asked, done = previous_task_steps()
        if done:
            lines += ["", "## Как это было сделано в прошлый раз", "Просьба: «{}»".format(asked)] + \
                     ["{}. {}".format(i, s) for i, s in enumerate(done, 1)]
    folder = skillbook.USER_DIR / slug(name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder / "SKILL.md"


def triggers_of(skill):
    """Слова сценария из шапки навыка. Раньше разбирались только с PyYAML — без него сценарии молча не запускались."""
    return list(skill.get("triggers") or [])


def match_trigger(command):
    """Сказано слово сценария («работаем», «Хлоя, работаем!») — навык этого сценария, иначе None."""
    said = norm(command)
    if not said or len(said) > 6:
        return None
    for s in skillbook.all_skills():
        if any(norm(t) == said for t in triggers_of(s)):
            return s
    return None


def lessons():
    return settings.get("lessons") or []


def learn_lesson(text):
    items = lessons()
    text = re.sub(r"\s+", " ", str(text)).strip()
    if text and text not in [x["text"] for x in items]:
        items.append({"text": text, "time": time.time()})
    settings.set("lessons", items[-MAX_LESSONS:])
    return len(settings.get("lessons"))


def forget_lesson(number):
    items = lessons()
    if not 1 <= int(number) <= len(items):
        return None
    gone = items.pop(int(number) - 1)
    settings.set("lessons", items)
    return gone["text"]


def lessons_prompt():
    items = lessons()
    if not items:
        return ""
    return ("Правила, которым тебя научил пользователь (выполняй их всегда; номер — для forget_lesson):\n" +
            "\n".join("{}. {}".format(i, x["text"]) for i, x in enumerate(items, 1)) + "\n")
