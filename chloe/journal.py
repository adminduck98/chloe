"""Журнал: всё, что Chloe услышала, сказала и сделала. Смотреть и удалять можно, изменять — нет."""
import base64
import json
import sqlite3
import threading
import time

from .brain import brain
from .config import DATA, JOURNAL_FILE, KEEP_SCREENS, OVERHEAR_DAYS
from .secret import redact


class Journal:
    """Журнал событий в SQLite. Ничего не скрыто: каждое действие можно посмотреть и удалить, но не изменить."""

    def __init__(self, path, screens):
        self.screens = screens
        self.screens.mkdir(exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, ts REAL NOT NULL, task INTEGER, kind TEXT NOT NULL,
            skill TEXT, title TEXT, detail TEXT, ok INTEGER DEFAULT 1, screen TEXT)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS events_skill ON events (skill, id)")
        self.db.commit()
        self.task = None

    def add(self, kind, skill, title, detail=None, ok=True, screen_png=None):
        """kind: heard / said / tool / confirm. Возвращает id события."""
        if kind == "heard":
            self.task = None   # новая просьба сама начинает задачу, а не продолжает прошлую
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO events (ts, task, kind, skill, title, detail, ok) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), self.task, kind, skill, redact(title)[:300],
                 redact(json.dumps(detail, ensure_ascii=False)) if detail is not None else None, int(ok)))
            eid = cur.lastrowid
            if screen_png and KEEP_SCREENS > 0:
                name = "{}.png".format(eid)
                (self.screens / name).write_bytes(screen_png)
                self.db.execute("UPDATE events SET screen = ? WHERE id = ?", (name, eid))
            self.db.commit()
        if kind == "heard":
            self.task = eid   # всё, что Chloe делает дальше, относится к этой просьбе
        brain.js("chloeEvent", self.summary(self.get(eid, full=False)))
        return eid

    @staticmethod
    def summary(row):
        return {k: row[k] for k in ("id", "ts", "task", "kind", "skill", "title", "ok")} | {"screen": bool(row["screen"])}

    def list(self, query="", skill="", limit=100, before=0):
        sql, args = "SELECT * FROM events WHERE 1", []
        if skill:
            sql += " AND skill = ?"
            args.append(skill)
        if query:
            sql += " AND (title LIKE ? OR detail LIKE ?)"
            args += ["%" + query + "%"] * 2
        if before:
            sql += " AND id < ?"
            args.append(before)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(min(int(limit), 500))
        with self.lock:
            return [self.summary(r) for r in self.db.execute(sql, args)]

    def get(self, eid, full=True):
        with self.lock:
            row = self.db.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
        if row is None or not full:
            return row
        out = self.summary(row)
        out["detail"] = json.loads(row["detail"]) if row["detail"] else None
        if row["screen"] and (self.screens / row["screen"]).exists():
            data = (self.screens / row["screen"]).read_bytes()
            kind = "jpeg" if data[:2] == b"\xff\xd8" else "png"   # новые скриншоты — JPEG
            out["screen"] = "data:image/{};base64,".format(kind) + base64.standard_b64encode(data).decode()
        else:
            out["screen"] = None
        if row["kind"] == "heard":   # вся просьба целиком: что было сделано в ответ
            with self.lock:
                out["steps"] = [self.summary(r) for r in self.db.execute(
                    "SELECT * FROM events WHERE task = ? AND id != ? ORDER BY id", (eid, eid))]
        return out

    def delete(self, eid):
        with self.lock:
            for r in self.db.execute("SELECT screen FROM events WHERE id = ? OR task = ?", (eid, eid)):
                if r["screen"]:
                    (self.screens / r["screen"]).unlink(missing_ok=True)
            # удаление просьбы удаляет и всё, что было сделано в ответ на неё
            self.db.execute("DELETE FROM events WHERE id = ? OR task = ?", (eid, eid))
            self.db.commit()
        return True

    def clear(self):
        with self.lock:
            self.db.execute("DELETE FROM events")
            self.db.commit()
        for f in self.screens.glob("*.png"):
            f.unlink(missing_ok=True)
        return True

    def talk(self, hours=6, limit=14):
        """Краткосрочная память: последние реплики разговора (просьбы и ответы), в том числе до перезапуска."""
        with self.lock:
            rows = self.db.execute("SELECT ts, kind, title FROM events WHERE kind IN ('heard', 'said') AND ts > ? "
                                   "ORDER BY id DESC LIMIT ?", (time.time() - hours * 3600, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def search_talk(self, query="", days=1, room=False, limit=60):
        """Что говорили: просьбы и ответы, а с room — и речь в комнате (не Хлое, офлайн-распознавание).
        Поиск — по словам без окончаний («машину» найдёт «машина»), регистр и ё/е не важны."""
        kinds = ("heard", "said", "overheard") if room else ("heard", "said")
        with self.lock:
            rows = self.db.execute("SELECT ts, kind, title FROM events WHERE kind IN ({}) AND ts > ? ORDER BY id DESC LIMIT 5000"
                                   .format(",".join("?" * len(kinds))), list(kinds) + [time.time() - days * 86400]).fetchall()
        norm = lambda t: str(t or "").lower().replace("ё", "е")
        stems = [w[:-1] if len(w) > 4 else w for w in norm(query).split() if len(w) > 2][:5]
        found = [dict(r) for r in rows if all(st in norm(r["title"]) for st in stems)]
        return list(reversed(found[:min(int(limit), 200)]))

    def forget_old_overheard(self, days):
        """Речь в комнате хранится days дней."""
        with self.lock:
            n = self.db.execute("DELETE FROM events WHERE kind = 'overheard' AND ts < ?", (time.time() - days * 86400,)).rowcount
            self.db.commit()
        return n

    def forget_old_screens(self):
        """Скриншоты хранятся KEEP_SCREENS дней: на них могут быть пароли и личное."""
        limit = time.time() - KEEP_SCREENS * 86400
        with self.lock:
            rows = self.db.execute("SELECT id, screen FROM events WHERE screen IS NOT NULL AND ts < ?", (limit,)).fetchall()
            for r in rows:
                (self.screens / r["screen"]).unlink(missing_ok=True)
                self.db.execute("UPDATE events SET screen = NULL WHERE id = ?", (r["id"],))
            self.db.commit()


journal = Journal(JOURNAL_FILE, DATA / "screens")
journal.forget_old_screens()
journal.forget_old_overheard(OVERHEAR_DAYS)
