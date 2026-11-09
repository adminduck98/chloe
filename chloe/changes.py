"""Изменения файлов: что Chloe создала, перезаписала, переместила, скопировала, удалила, скачала — и отмена.

Отмена сама ничего не стирает насовсем: лишнее уходит в Корзину, а файл, который Chloe заменила,
перед заменой откладывается в ~/.chloe/backups и при отмене возвращается на место.
"""
import pathlib
import shutil
import sqlite3
import threading
import time
import urllib.parse

from .brain import brain
from .config import BACKUPS_DIR, HOME, JOURNAL_FILE, OS_NAME
from .journal import journal

ACTIONS = {   # действие → как его назвать человеку
    "create_folder": "Создана папка",
    "write_new": "Создан файл",
    "overwrite": "Перезаписан файл",
    "move": "Перемещено",
    "copy": "Скопировано",
    "delete": "Удалено в корзину",
    "download": "Скачано",
}


def short(p):
    try:
        return "~/" + str(pathlib.Path(p).relative_to(HOME))
    except ValueError:
        return str(p)


def to_trash(path):
    from send2trash import send2trash

    send2trash(str(path))


def restore_from_trash(original):
    """Возвращает из Корзины (Linux, стандарт freedesktop): ищет самую свежую запись с этим путём."""
    if OS_NAME != "Linux":
        return False
    trash = HOME / ".local/share/Trash"
    best = None
    for info in (trash / "info").glob("*.trashinfo"):
        fields = dict(line.split("=", 1) for line in info.read_text(errors="replace").splitlines() if "=" in line)
        if urllib.parse.unquote(fields.get("Path", "")) == str(original):
            date = fields.get("DeletionDate", "")
            if best is None or date > best[0]:
                best = (date, info)
    if best is None:
        return False
    info = best[1]
    stored = trash / "files" / info.name[: -len(".trashinfo")]
    if not stored.exists():
        return False
    pathlib.Path(original).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(stored), str(original))
    info.unlink()
    return True


class Changes:
    """Таблица changes в той же базе, что и журнал."""

    def __init__(self, path, backups):
        self.backups = backups
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY, ts REAL NOT NULL, action TEXT NOT NULL,
            src TEXT, dst TEXT, backup TEXT, undone REAL, note TEXT)""")
        self.db.commit()

    def set_aside(self, path):
        """Файл или папка, которые сейчас будут заменены, переезжают в backups — чтобы отмена могла их вернуть."""
        self.backups.mkdir(parents=True, exist_ok=True)
        spot = self.backups / "{}-{}".format(time.strftime("%Y%m%d-%H%M%S"), pathlib.Path(path).name)
        n = 2
        while spot.exists():
            spot = spot.with_name("{}-{}".format(n, spot.name))
            n += 1
        shutil.move(str(path), str(spot))
        return spot

    def record(self, action, src=None, dst=None, backup=None):
        with self.lock:
            cur = self.db.execute("INSERT INTO changes (ts, action, src, dst, backup) VALUES (?, ?, ?, ?, ?)",
                                  (time.time(), action, str(src) if src else None, str(dst) if dst else None,
                                   str(backup) if backup else None))
            self.db.commit()
            cid = cur.lastrowid
        brain.js("chloeChange", self.view(self.get(cid)))
        return cid

    def get(self, cid):
        with self.lock:
            return self.db.execute("SELECT * FROM changes WHERE id = ?", (cid,)).fetchone()

    @staticmethod
    def describe(row):
        what = ACTIONS.get(row["action"], row["action"])
        if row["action"] in ("move", "copy"):
            return "{}: {} → {}".format(what, short(row["src"]), short(row["dst"]))
        return "{}: {}".format(what, short(row["dst"] or row["src"]))

    def view(self, row):
        """Для окна: что сделано, когда, можно ли отменить."""
        return {"id": row["id"], "ts": row["ts"], "action": row["action"], "text": self.describe(row),
                "src": row["src"], "dst": row["dst"], "undone": row["undone"], "note": row["note"],
                "folder": str(pathlib.Path(row["dst"] or row["src"]).parent)}

    def list(self, limit=100):
        with self.lock:
            rows = self.db.execute("SELECT * FROM changes ORDER BY id DESC LIMIT ?", (min(int(limit), 500),)).fetchall()
        return [self.view(r) for r in rows]

    def last_open(self):
        with self.lock:
            return self.db.execute("SELECT * FROM changes WHERE undone IS NULL ORDER BY id DESC LIMIT 1").fetchone()

    def undo(self, cid, by="окно"):
        """Отменяет изменение. Возвращает (получилось ли, что сказать человеку)."""
        row = self.get(cid)
        if row is None:
            return False, "Такого изменения нет."
        if row["undone"]:
            return False, "Это уже отменено."
        try:
            ok, message = self._undo(row)
        except Exception as e:
            ok, message = False, "Не получилось: " + str(e)
        if ok:
            with self.lock:
                self.db.execute("UPDATE changes SET undone = ?, note = ? WHERE id = ?", (time.time(), message, cid))
                self.db.commit()
        journal.add("files", "Файлы", ("Отменено: " if ok else "Не отменено: ") + self.describe(row),
                    {"change": cid, "result": message, "by": by}, ok=ok)
        return ok, message

    def _undo(self, row):
        action = row["action"]
        src = pathlib.Path(row["src"]) if row["src"] else None
        dst = pathlib.Path(row["dst"]) if row["dst"] else None
        backup = pathlib.Path(row["backup"]) if row["backup"] else None

        if action == "delete":
            if src.exists():
                return False, "На этом месте уже есть {} — сначала уберите его.".format(short(src))
            if restore_from_trash(src):
                return True, "Вернула из корзины: " + short(src)
            return False, "Не нашла {} в Корзине — возможно, её очистили. Откройте Корзину вручную.".format(src.name)

        if action == "move":
            if not dst.exists():
                return False, "{} уже нет на новом месте.".format(short(dst))
            if src.exists():
                return False, "На старом месте уже есть {} — не хочу его затирать.".format(short(src))
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
            if backup and backup.exists():
                shutil.move(str(backup), str(dst))
                return True, "Вернула на место {} и восстановила то, что было в {}.".format(short(src), short(dst))
            return True, "Вернула на место: " + short(src)

        if action == "create_folder":
            if not dst.exists():
                return True, "Папки {} уже нет.".format(short(dst))
            if not any(dst.iterdir()):
                dst.rmdir()
                return True, "Убрала пустую папку " + short(dst)
            to_trash(dst)
            return True, "Папка была не пустой — убрала её в корзину: " + short(dst)

        # create / overwrite / copy / download: то, что появилось, — в корзину; заменённое — обратно
        if dst.exists():
            to_trash(dst)
        if backup and backup.exists():
            shutil.move(str(backup), str(dst))
            return True, "Вернула прежнюю версию: " + short(dst)
        return True, "Убрала в корзину: " + short(dst)

    def forget_old_backups(self, days=30):
        """Копии старше 30 дней — в Корзину (не насовсем: оттуда их ещё можно достать)."""
        limit = time.time() - days * 86400
        for f in self.backups.glob("*") if self.backups.exists() else []:
            try:
                if f.stat().st_mtime < limit:
                    to_trash(f)
            except Exception:
                pass


changes = Changes(JOURNAL_FILE, BACKUPS_DIR)
changes.forget_old_backups()
