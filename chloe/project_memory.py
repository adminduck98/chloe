"""Память проектов (PROJECT INTELLIGENCE): задачи, решения, идеи и цели каждого проекта.

«Хлоя, продолжим проект Chloe» — Chloe собирает картину: что сделано, что в работе, что решено, — и предлагает
следующий шаг. Задачи меняются по просьбе или подтверждению пользователя. Хранится в ~/.chloe/chloe.db
(таблицы proj_tasks и proj_notes) — попадает в ежедневные копии вместе с журналом и базой знаний.
"""
import sqlite3
import threading
import time

from .config import JOURNAL_FILE

STATUS = ("todo", "doing", "done")
STATUS_RU = {"todo": "сделать", "doing": "в работе", "done": "готово"}
PRIORITY_RU = {1: "важно", 2: "обычно", 3: "потом"}
KINDS = {"decision": "решение", "idea": "идея", "goal": "цель"}


def key_of(name):
    return " ".join(str(name or "").lower().replace("ё", "е").split())


class ProjectMemory:
    def __init__(self, path):
        self.lock = threading.RLock()   # resolve() внутри add_task берёт тот же замок
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS proj_tasks (
            id INTEGER PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo',
            priority INTEGER NOT NULL DEFAULT 2, created REAL, updated REAL, done_at REAL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS proj_notes (
            id INTEGER PRIMARY KEY, project TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, ts REAL)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS proj_tasks_project ON proj_tasks (project, status)")
        self.db.commit()

    # --- какие проекты известны памяти ---
    def projects(self):
        with self.lock:
            rows = self.db.execute("SELECT project FROM proj_tasks UNION SELECT project FROM proj_notes").fetchall()
        return sorted({r[0] for r in rows})

    def resolve(self, name):
        """Имя проекта в памяти: точное, или единственное похожее («хлоя» ≠ «chloe» — сравниваем и вхождение)."""
        k = key_of(name)
        known = self.projects()
        if k in known:
            return k
        near = [p for p in known if k and (k in p or p in k)]
        return near[0] if len(near) == 1 else k

    # --- задачи ---
    def add_task(self, project, title, priority=2):
        now = time.time()
        with self.lock:
            cur = self.db.execute("INSERT INTO proj_tasks (project, title, status, priority, created, updated) VALUES (?, ?, 'todo', ?, ?, ?)",
                                  (self.resolve(project), title.strip(), int(priority) if int(priority) in PRIORITY_RU else 2, now, now))
            self.db.commit()
            return cur.lastrowid

    def task(self, tid):
        with self.lock:
            r = self.db.execute("SELECT * FROM proj_tasks WHERE id = ?", (tid,)).fetchone()
        return dict(r) if r else None

    def set_status(self, tid, status):
        if status not in STATUS:
            raise ValueError("статус: " + ", ".join(STATUS))
        now = time.time()
        with self.lock:
            self.db.execute("UPDATE proj_tasks SET status = ?, updated = ?, done_at = ? WHERE id = ?",
                            (status, now, now if status == "done" else None, tid))
            self.db.commit()

    def edit_task(self, tid, title=None, priority=None):
        with self.lock:
            if title:
                self.db.execute("UPDATE proj_tasks SET title = ?, updated = ? WHERE id = ?", (title.strip(), time.time(), tid))
            if priority in PRIORITY_RU:
                self.db.execute("UPDATE proj_tasks SET priority = ?, updated = ? WHERE id = ?", (priority, time.time(), tid))
            self.db.commit()

    def delete_task(self, tid):
        with self.lock:
            self.db.execute("DELETE FROM proj_tasks WHERE id = ?", (tid,))
            self.db.commit()

    def tasks(self, project, status=None):
        sql = "SELECT * FROM proj_tasks WHERE project = ?" + (" AND status = ?" if status else "") + \
              " ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END, priority, " \
              "CASE status WHEN 'done' THEN -done_at ELSE created END"
        args = (self.resolve(project), status) if status else (self.resolve(project),)
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    # --- решения, идеи, цели ---
    def add_note(self, project, kind, text):
        if kind not in KINDS:
            raise ValueError("вид записи: " + ", ".join(KINDS))
        with self.lock:
            cur = self.db.execute("INSERT INTO proj_notes (project, kind, text, ts) VALUES (?, ?, ?, ?)",
                                  (self.resolve(project), kind, text.strip(), time.time()))
            self.db.commit()
            return cur.lastrowid

    def notes(self, project, limit=20):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM proj_notes WHERE project = ? ORDER BY ts DESC LIMIT ?",
                                                      (self.resolve(project), limit))]

    def important_open(self, limit=3):
        """Важные незакрытые задачи всех проектов — Chloe называет их при включении."""
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT * FROM proj_tasks WHERE priority = 1 AND status != 'done' ORDER BY status = 'doing' DESC, created LIMIT ?", (limit,))]

    def delete_note(self, nid):
        with self.lock:
            self.db.execute("DELETE FROM proj_notes WHERE id = ?", (nid,))
            self.db.commit()


project_memory = ProjectMemory(JOURNAL_FILE)
