"""Настоящий сон: ночью, когда к Chloe давно не обращались, она приводит память в порядок.

Что делает (и только это показывает мозг — без случайных вспышек):
1. Объединяет повторяющиеся воспоминания: одинаковые или почти одинаковые, и такие, где одно — часть другого
   («Любит кофе» и «Любит чёрный кофе без сахара» → остаётся полное).
2. Укрепляет важное: воспоминания, которые за последний месяц реально пригождались (в журнале «Вспомнила: …»),
   помечаются важными и всегда попадают в подсказку, даже когда воспоминаний станет много.
3. Переигрывает настоящие задачи дня (из журнала) — так закрепляются её привычные пути.

Ничего не теряется насовсем: перед уборкой копия памяти кладётся в ~/.chloe/sleep/, а в журнале видно,
что с чем объединено. Когда: с 1 до 6 ночи, если 20 минут тишины и сегодня ещё не спала; или по просьбе «Хлоя, иди спать».
"""
import difflib
import json
import re
import threading
import time

from .brain import brain
from .config import DATA
from .journal import journal
from .memory import memory
from .settings import settings
from .topics import apply_to_memory, find_topics
from .signals import busy

SLEEP_DIR = DATA / "sleep"
NIGHT = (1, 6)            # с 1 до 6 часов
QUIET_MINUTES = 20        # столько тишины перед сном
IMPORTANT_RECALLS = 2     # столько раз пригодилось за месяц — важное


def norm(text):
    return re.sub(r"[^\w ]", "", text.lower().replace("ё", "е")).strip()


def words5(text):
    """Слова от 3 букв по первым 5 буквам: «чёрный»/«черного» → «черны», «кофе» → «кофе»."""
    return {w[:5] for w in re.findall(r"\w+", norm(text)) if len(w) >= 3}


def kind_of(a, b):
    """"same" — повторяют друг друга; "part" — a целиком входит в b; None — разные."""
    na, nb = norm(a["text"]), norm(b["text"])
    if not na or not nb:
        return None
    if na == nb or difflib.SequenceMatcher(None, na, nb).ratio() >= 0.85:
        return "same"
    wa, wb = words5(a["text"]), words5(b["text"])
    if len(wa) >= 2 and wa < wb:
        return "part"
    return None


def find_merges(items):
    """[(оставить, убрать)]. Остаётся более полное; из одинаковых — то, что уже оставлено, иначе самое свежее."""
    merges, dropped, kept = [], set(), set()
    fresh = lambda m: (m.get("edited") or m.get("time") or "", m["id"])
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a["id"] in dropped or b["id"] in dropped:
                continue
            if kind_of(a, b) == "part":
                keep, drop = b, a
            elif kind_of(b, a) == "part":
                keep, drop = a, b
            elif kind_of(a, b) == "same":
                if a["id"] in kept or b["id"] in kept:
                    keep = a if a["id"] in kept else b
                else:
                    keep = max((a, b), key=fresh)
                drop = b if keep is a else a
            else:
                continue
            merges.append((keep, drop))
            dropped.add(drop["id"])
            kept.add(keep["id"])
    return merges


def recall_counts(days=30):
    since = time.time() - days * 86400
    with journal.lock:
        rows = journal.db.execute("SELECT title FROM events WHERE kind = 'memory' AND title LIKE 'Вспомнила: %' AND ts > ?",
                                  (since,)).fetchall()
    counts = {}
    for r in rows:
        text = r["title"][len("Вспомнила: "):]
        counts[text] = counts.get(text, 0) + 1
    return counts


def todays_tasks(limit=12):
    """Настоящие задачи за сегодня с шагами — для повтора в быстром сне."""
    from .tools.replay import steps_of

    start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
    with journal.lock:
        asks = journal.db.execute(
            "SELECT id, title FROM events WHERE kind = 'heard' AND ts > ? AND EXISTS "
            "(SELECT 1 FROM events t WHERE t.task = events.id AND t.kind = 'tool') ORDER BY id DESC LIMIT ?",
            (start - 86400 / 4, limit)).fetchall()
    return [{"title": a["title"], "steps": steps_of(a["id"])} for a in reversed(asks)]


namer = None   # быстрая модель для названий тем; задаёт app.py (без неё — название из самых частых слов)


def consolidate():
    """Уборка памяти. Возвращает отчёт: что объединено, что стало важным, какие задачи дня переиграть."""
    items = list(memory.items)
    SLEEP_DIR.mkdir(exist_ok=True)
    backup = SLEEP_DIR / time.strftime("memory-%Y-%m-%d-%H%M.json")
    backup.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    merged = []
    for keep, drop in find_merges(items):
        memory.delete(drop["id"])
        merged.append({"keep": keep["text"], "drop": drop["text"]})
        journal.add("sleep", "Сон", "Объединила: «{}» → «{}»".format(drop["text"], keep["text"]),
                    {"keep": keep, "drop": drop, "backup": str(backup)})

    counts = recall_counts()
    strong = []
    for m in memory.items:
        important = counts.get(m["text"], 0) >= IMPORTANT_RECALLS
        if important and not m.get("important"):
            strong.append(m["text"])
        if important != bool(m.get("important")):
            memory.mark(m["id"], important)
    for text in strong:
        journal.add("sleep", "Сон", "Укрепила важное: " + text, {"text": text, "recalls": counts.get(text, 0)})

    zones = find_topics(namer)
    moved = apply_to_memory(zones)
    before = settings.get("topic_names") or []
    for name, members in zones.items():
        if name not in before:
            journal.add("sleep", "Сон", "Новая тема: {} ({})".format(name, ", ".join(m.get("name") or m.get("text") for m in members[:6])),
                        {"topic": name, "members": members})
    settings.set("topic_names", sorted(zones))

    report = {"merged": merged, "strong": strong, "tasks": todays_tasks(), "zones": zones, "moved": moved}
    journal.add("sleep", "Сон", "Сон: объединила {}, укрепила {}, переиграла задач дня: {}, тем: {}".format(
        len(merged), len(strong), len(report["tasks"]), len(zones)), {"merged": len(merged), "strong": strong, "backup": str(backup),
                                                                     "topics": sorted(zones)})
    if not merged:   # копия не понадобилась — не копим лишнее
        backup.unlink(missing_ok=True)
    return report


def go_to_sleep():
    """Уснуть сейчас: убрать память и показать это в мозге."""
    settings.set("slept_on", time.strftime("%Y-%m-%d"))
    report = consolidate()
    brain.state("sleeping")
    brain.js("chloeSleep", report)
    return report


def watcher():
    """Поток: раз в минуту — не пора ли спать."""
    while True:
        time.sleep(60)
        try:
            if should_sleep():
                print("[сон: привожу память в порядок]")
                go_to_sleep()
        except Exception as e:
            print("[сон: " + str(e)[:80] + "]")


def should_sleep(now=None):
    """Ночь, давно тихо, Chloe не занята и сегодня ещё не спала."""
    now = now or time.time()
    t = time.localtime(now)
    return (NIGHT[0] <= t.tm_hour < NIGHT[1] and now - journal_last() > QUIET_MINUTES * 60 and not busy.is_set()
            and settings.get("slept_on") != time.strftime("%Y-%m-%d", t))


def journal_last():
    with journal.lock:
        row = journal.db.execute("SELECT MAX(ts) AS t FROM events WHERE kind IN ('heard', 'tool', 'said')").fetchone()
    return row["t"] or 0


def start():
    threading.Thread(target=watcher, daemon=True, name="sleep").start()
