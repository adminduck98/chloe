"""Knowledge & Memory: граф связей и Timeline — что с чем связано и что когда происходило.

Узлы берутся из того, что Chloe уже хранит (ничего не дублируется): проекты, задачи, решения / идеи / цели,
изученные документы, воспоминания. Связи трёх видов:
- «в проекте» — задача или запись принадлежит проекту;
- «похоже» — находятся сами, по общим редким словам (с названием слов-причин: связь всегда объяснима);
- «вручную» — их добавляет пользователь («свяжи этот документ с задачей…»); лишнюю авто-связь можно скрыть.
Timeline — те же объекты по времени: задача появилась / сделана, записано решение, изучен документ, запомнено.
Свои таблицы — только graph_links и graph_hidden в ~/.chloe/chloe.db.
"""
import math
import re
import sqlite3
import threading
import time

from .config import JOURNAL_FILE
from .knowledge import STOP, _stem

TYPES = {"project": "проект", "task": "задача", "decision": "решение", "idea": "идея", "goal": "цель",
         "doc": "документ", "memory": "воспоминание"}
MAX_AUTO = 4             # авто-связей на узел: больше — уже шум
MIN_SCORE = 2.2          # порог похожести (сумма редкости общих слов)
EXTRA_STOP = {"chloe", "хлоя", "хлои", "будущ", "концеп", "может", "должн", "главн", "идея", "идеи", "проек", "польз",
              "через", "после", "котор", "можно", "нужно", "когда", "чтобы", "этого", "такой", "инстр", "систе",
              "толь", "chlo", "рабо", "зада", "прое", "выпол", "гото", "созд", "свое", "свой", "буде", "есть", "боль", "сейч"}


def words(text):
    """Значимые основы слов текста."""
    out = set()
    for w in re.findall(r"[a-zа-яё0-9]+", (text or "").lower().replace("ё", "е")):
        if len(w) < 4 or w in STOP:
            continue
        s = _stem(w)
        if s[:5] not in EXTRA_STOP and s not in EXTRA_STOP:
            out.add(s)
    return out


class Graph:
    def __init__(self, path=JOURNAL_FILE, sources=None):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS graph_links (a TEXT NOT NULL, b TEXT NOT NULL, note TEXT, ts REAL, PRIMARY KEY (a, b))")
        self.db.execute("CREATE TABLE IF NOT EXISTS graph_hidden (a TEXT NOT NULL, b TEXT NOT NULL, PRIMARY KEY (a, b))")
        self.db.commit()
        self.sources = sources        # для тестов: функция → список узлов
        self._built = (0, None)

    # --- узлы ---
    def _collect(self):
        if self.sources:
            return self.sources()
        from .knowledge import knowledge
        from .memory import memory
        from .project_memory import project_memory as pm

        nodes = []
        for name in pm.projects():
            tasks = pm.tasks(name)
            nodes.append({"id": "project:" + name, "type": "project", "title": name, "text": "",
                          "ts": min([t["created"] or 0 for t in tasks] or [0]) or None})
            for t in tasks:
                nodes.append({"id": "task:{}".format(t["id"]), "type": "task", "title": t["title"], "text": "", "ts": t["created"],
                              "project": name, "status": t["status"], "done_at": t["done_at"]})
            for n in pm.notes(name, 500):
                nodes.append({"id": "note:{}".format(n["id"]), "type": n["kind"] if n["kind"] in TYPES else "idea",
                              "title": n["text"][:90], "text": n["text"], "ts": n["ts"], "project": name})
        for d in knowledge.docs():
            with knowledge.lock:
                rows = knowledge.db.execute("SELECT text FROM kb_chunks WHERE doc_id = ? LIMIT 2", (d["id"],)).fetchall()
            nodes.append({"id": "doc:{}".format(d["id"]), "type": "doc", "title": d["title"], "ts": d["added"],
                          "text": " ".join(r[0] for r in rows)[:1500], "path": d["path"]})
        for m in memory.items:
            try:
                ts = time.mktime(time.strptime(m.get("time", ""), "%Y-%m-%d %H:%M"))
            except (ValueError, TypeError):
                ts = None
            nodes.append({"id": "memory:{}".format(m["id"]), "type": "memory", "title": m["text"][:90], "text": m["text"],
                          "ts": ts, "zone": m.get("zone")})
        return nodes

    # --- связи ---
    def build(self, fresh=False):
        """(узлы по id, связи) — кеш на 20 секунд: панель и инструмент не пересчитывают граф на каждый клик."""
        with self.lock:
            if not fresh and self._built[1] and time.time() - self._built[0] < 20:
                return self._built[1]
            nodes = {n["id"]: n for n in self._collect()}
            edges = {}

            def add(a, b, kind, why=""):
                if a == b or a not in nodes or b not in nodes:
                    return
                key = tuple(sorted((a, b)))
                if key not in edges or kind == "manual":
                    edges[key] = {"a": key[0], "b": key[1], "kind": kind, "why": why}

            for n in nodes.values():
                if n.get("project"):
                    add(n["id"], "project:" + n["project"], "project", "в проекте")
            self._auto(nodes, add)
            hidden = {tuple(r) for r in self.db.execute("SELECT a, b FROM graph_hidden")}
            for key in [k for k, e in edges.items() if e["kind"] == "auto" and k in hidden]:
                del edges[key]
            for a, b, note in self.db.execute("SELECT a, b, note FROM graph_links"):
                add(a, b, "manual", note or "связано вручную")
            self._built = (time.time(), (nodes, list(edges.values())))
            return self._built[1]

    def _auto(self, nodes, add):
        """Похожие узлы: общие редкие слова. Задачи и записи одного проекта друг с другом не сравниваются по названию
        проекта — только по содержанию."""
        items = [n for n in nodes.values() if n["type"] != "project"]
        bags = {n["id"]: words(n["title"] + " " + n.get("text", "")) for n in items}
        titles = {n["id"]: words(n["title"]) for n in items}
        df = {}
        for bag in bags.values():
            for w in bag:
                df[w] = df.get(w, 0) + 1
        total = max(1, len(items))
        idf = {w: math.log(1 + total / c) for w, c in df.items()}
        rare = max(3, total // 8)
        best = {}
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                common = {w for w in bags[a["id"]] & bags[b["id"]] if df[w] <= rare}   # частые слова связью не считаются
                if len(common) < 2:
                    continue
                if not common & titles[a["id"]] or not common & titles[b["id"]]:       # общее слово — в обоих заголовках
                    continue
                score = sum(idf[w] for w in common)
                if score < MIN_SCORE:
                    continue
                why = ", ".join(sorted(common, key=lambda w: -idf[w])[:4])
                best.setdefault(a["id"], []).append((score, b["id"], why))
                best.setdefault(b["id"], []).append((score, a["id"], why))
        for a, lst in best.items():
            for score, b, why in sorted(lst, reverse=True)[:MAX_AUTO]:
                add(a, b, "auto", "общее: " + why)

    # --- запросы ---
    def find(self, query, limit=6):
        """Узлы по id («task:25»), типу и номеру («задача 25») или словам из названия."""
        nodes, _ = self.build()
        q = (query or "").strip()
        if q in nodes:
            return [nodes[q]]
        m = re.match(r"^(проект|задач\w*|решени\w*|иде\w*|цел\w*|документ\w*|воспоминани\w*)\s*[№#]?\s*(\d+)$", q.lower())
        if m:
            kind = {"зад": "task", "реш": "note", "иде": "note", "цел": "note", "док": "doc", "вос": "memory"}.get(m.group(1)[:3])
            if kind and "{}:{}".format(kind, m.group(2)) in nodes:
                return [nodes["{}:{}".format(kind, m.group(2))]]
        want = words(q) or {w for w in re.findall(r"\w+", q.lower()) if len(w) > 1}
        if not want:
            return []
        scored = []
        for n in nodes.values():
            title = words(n["title"]) | {n["title"].lower()}
            hit = len(want & title) * 2 + len(want & words(n.get("text", "")))
            if q.lower() in n["title"].lower():
                hit += 3
            if hit:
                scored.append((hit, n.get("ts") or 0, n))
        return [n for _, _, n in sorted(scored, key=lambda x: (-x[0], -x[1]))[:limit]]

    def neighbors(self, node_id):
        nodes, edges = self.build()
        out = []
        for e in edges:
            if node_id in (e["a"], e["b"]):
                other = nodes[e["b"] if e["a"] == node_id else e["a"]]
                out.append({"node": other, "kind": e["kind"], "why": e["why"]})
        rank = {"manual": 0, "auto": 1, "project": 2}
        return sorted(out, key=lambda x: (rank[x["kind"]], -(x["node"].get("ts") or 0)))

    def link(self, a, b, note=None):
        nodes, _ = self.build()
        if a not in nodes or b not in nodes or a == b:
            return False
        key = tuple(sorted((a, b)))
        with self.lock:
            self.db.execute("DELETE FROM graph_hidden WHERE a = ? AND b = ?", key)
            self.db.execute("INSERT OR REPLACE INTO graph_links (a, b, note, ts) VALUES (?, ?, ?, ?)", key + (note, time.time()))
            self.db.commit()
            self._built = (0, None)
        return True

    def unlink(self, a, b):
        """Ручная связь удаляется; авто-связь скрывается (чтобы не появилась снова). Связь «в проекте» не трогается."""
        key = tuple(sorted((a, b)))
        with self.lock:
            n = self.db.execute("DELETE FROM graph_links WHERE a = ? AND b = ?", key).rowcount
            _, edges = self.build(fresh=True)
            auto = any((e["a"], e["b"]) == key and e["kind"] == "auto" for e in edges)
            if auto:
                self.db.execute("INSERT OR IGNORE INTO graph_hidden (a, b) VALUES (?, ?)", key)
            self.db.commit()
            self._built = (0, None)
        return bool(n or auto)

    def timeline(self, project=None, query=None, days=None, limit=60, now=None):
        """События от новых к старым: [{ts, what, node}]."""
        nodes, _ = self.build()
        now = now or time.time()
        keep = None
        if query:
            found = self.find(query, 3)
            keep = {n["id"] for n in found} | {x["node"]["id"] for n in found for x in self.neighbors(n["id"])}
        events = []
        for n in nodes.values():
            if n["type"] == "project" or (project and n.get("project") != project and n["id"] not in (keep or ())):
                continue
            if keep is not None and n["id"] not in keep:
                continue
            verb = {"task": "появилась задача", "decision": "решили", "idea": "идея", "goal": "цель",
                    "doc": "изучен документ", "memory": "запомнила"}[n["type"]]
            if n.get("ts"):
                events.append({"ts": n["ts"], "what": verb, "node": n})
            if n.get("done_at"):
                events.append({"ts": n["done_at"], "what": "сделана задача", "node": n})
        if days:
            events = [e for e in events if now - e["ts"] <= days * 86400]
        return sorted(events, key=lambda e: -e["ts"])[:limit]

    def stats(self):
        nodes, edges = self.build()
        by = {}
        for n in nodes.values():
            by[n["type"]] = by.get(n["type"], 0) + 1
        kinds = {}
        for e in edges:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        return {"nodes": len(nodes), "edges": len(edges), "types": by, "kinds": kinds}


def label(n):
    return "{} «{}» [{}]".format(TYPES.get(n["type"], n["type"]), n["title"][:80], n["id"])


graph = Graph()
