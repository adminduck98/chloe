"""Зоны по смыслу: темы складываются сами из настоящей работы Chloe.

Что встречается вместе в одних и тех же задачах за месяц (программы, сайты, папки, люди, места
и воспоминания, которые пригодились), — одна тема. Например: сайт pointtech.uz, папка ~/Документы/Магазин,
Ахмед в Telegram и воспоминание «Работает в магазине POINT TECH» → зона «Магазин POINT TECH».
Воспоминание, которое ещё ни разу не пригодилось, попадает в тему, если его слова есть в задачах этой темы.

Навыки остаются на своих местах (они общие для всех тем). Темы пересчитываются во сне;
тема, которая почти не изменилась, сохраняет своё имя, чтобы мозг не перекраивался каждую ночь.
"""
import json
import re
import time
from collections import Counter, defaultdict

from .experience import things_of
from .journal import journal
from .memory import memory
from .settings import settings

MIN_TOPIC = 3      # меньше — не тема, предметы остаются в своих зонах («Сайты», «Папки»…)
DAYS = 30
STOP = {"хлоя", "хлои", "открой", "найди", "покажи", "сделай", "пожалуйста", "можешь", "скажи", "давай", "который",
        "какой", "какая", "какие", "сколько", "сейчас", "сегодня", "завтра", "потом", "этот", "это", "там", "тут",
        "мне", "меня", "мой", "моя", "мои", "для", "что", "как", "где", "все", "всё", "его", "она", "они", "через"}


def words(text):
    return [w for w in re.findall(r"[a-zа-яё0-9]+", text.lower().replace("ё", "е")) if len(w) >= 4 and w not in STOP]


def stem(w):
    return w[:5]


def tasks(days=DAYS):
    """[(текст просьбы, {ключ предмета})] за последние дни. Ключ: ("w", имя предмета) или ("m", текст воспоминания)."""
    since = time.time() - days * 86400
    with journal.lock:
        rows = journal.db.execute(
            "SELECT e.task, e.kind, e.title, e.detail, e.ok, h.title AS ask FROM events e JOIN events h ON h.id = e.task "
            "WHERE e.ts > ? AND e.kind IN ('tool', 'memory') ORDER BY e.id", (since,)).fetchall()
    by_task = defaultdict(lambda: ["", set()])
    for r in rows:
        t = by_task[r["task"]]
        t[0] = r["ask"]
        if r["kind"] == "tool":
            d = json.loads(r["detail"] or "{}")
            for th in things_of(d.get("tool", ""), d.get("args") or {}, bool(r["ok"])):
                t[1].add(("w", th["name"]))
        elif r["title"].startswith("Вспомнила: "):
            t[1].add(("m", r["title"][len("Вспомнила: "):]))
    return [(text, items) for text, items in by_task.values() if items]


def build_graph(task_list, memories):
    """Вес связи двух предметов = сколько раз они встретились в одной задаче (+0.5 за общие слова воспоминания и задачи)."""
    w = defaultdict(float)
    texts = {}
    for text, items in task_list:
        for k in items:
            texts.setdefault(k, []).append(text)
    for i, (text, items) in enumerate(task_list):
        items = set(items)
        task_stems = {stem(x) for x in words(text)}
        for m in memories:   # воспоминание, которое ещё не пригодилось, но говорит о том же
            key = ("m", m["text"])
            if key not in items and len({stem(x) for x in words(m["text"])} & task_stems) >= 1:
                for k in items:
                    w[tuple(sorted((key, k)))] += 0.5
                texts.setdefault(key, []).append(text)
        items = sorted(items)
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                w[(items[a], items[b])] += 1
    return w, texts


def clusters(w):
    """Распространение меток: каждый предмет берёт тему соседей с самым большим весом. Детерминированно."""
    nbr = defaultdict(dict)
    for (a, b), x in w.items():
        nbr[a][b] = nbr[a].get(b, 0) + x
        nbr[b][a] = nbr[b].get(a, 0) + x
    label = {n: n for n in nbr}
    for _ in range(15):
        changed = False
        for n in sorted(nbr):
            score = defaultdict(float)
            for m, x in nbr[n].items():
                score[label[m]] += x
            best = max(sorted(score), key=lambda lb: score[lb])
            if score[best] > score.get(label[n], 0) and best != label[n]:
                label[n], changed = best, True
        if not changed:
            break
    groups = defaultdict(set)
    for n, lb in label.items():
        groups[lb].add(n)
    return [g for g in groups.values() if len(g) >= MIN_TOPIC]


def keyword_name(group, texts):
    """Название без модели: самое частое значимое слово задач этой темы, в самой частой форме."""
    counts, forms = Counter(), defaultdict(Counter)
    for k in group:
        for text in texts.get(k, []):
            for x in set(words(text)):
                counts[stem(x)] += 1
                forms[stem(x)][x] += 1
        for x in words(k[1]):   # имена предметов и воспоминаний тоже говорят о теме
            counts[stem(x)] += 0.5
            forms[stem(x)][x] += 1
    if not counts:
        return None
    top = counts.most_common(1)[0][0]
    return forms[top].most_common(1)[0][0].capitalize()


def ask_name(namer, group, texts):
    """Короткое название темы от быстрой модели; None — модели нет или ответила странно."""
    if namer is None:
        return None
    asks = sorted({t for k in group for t in texts.get(k, [])})[:8]
    things = [k[1] for k in sorted(group)][:12]
    prompt = ("Это одна тема из работы ассистента с пользователем. Просьбы: {}. Предметы и воспоминания: {}. "
              "Назови тему 1–3 словами по-русски (например «Магазин POINT TECH», «Учёба», «Музыка»). "
              "Ответь только названием, без кавычек и точки.").format("; ".join(asks), "; ".join(things))
    try:
        name = (namer(prompt) or "").strip().strip("«»\"'.").strip()
    except Exception:
        return None
    return name if 0 < len(name) <= 32 and "\n" not in name else None


def find_topics(namer=None):
    """{название: [{"kind": "memory"|"world", ...}]}. Старые темы, почти не изменившиеся, сохраняют название."""
    old = settings.get("topics") or {}
    task_list = tasks()
    w, texts = build_graph(task_list, memory.items)
    out, used = {}, set()
    for group in sorted(clusters(w), key=lambda g: -len(g)):
        keys = sorted("{}:{}".format(*k) for k in group)
        name = None
        for old_name, old_keys in old.items():   # та же тема, что вчера?
            if old_name not in used and len(set(keys) & set(old_keys)) * 2 >= max(len(keys), len(old_keys)):
                name = old_name
                break
        name = name or ask_name(namer, group, texts) or keyword_name(group, texts) or "Тема"
        while name in used:
            name += " 2"
        used.add(name)
        out[name] = sorted(group)
    settings.set("topics", {n: sorted("{}:{}".format(*k) for k in g) for n, g in out.items()})
    return {n: [{"kind": "memory", "text": k[1]} if k[0] == "m" else {"kind": "world", "name": k[1]} for k in g]
            for n, g in out.items()}


def apply_to_memory(topics):
    """Воспоминания получают зону своей темы — её видно и в панели «Память». Возвращает, сколько изменилось."""
    changed = 0
    for name, members in topics.items():
        for m in members:
            if m["kind"] == "memory":
                item = next((x for x in memory.items if x["text"] == m["text"]), None)
                if item is not None and item.get("zone") != name:
                    memory.set_zone(item["id"], name)
                    changed += 1
    return changed
