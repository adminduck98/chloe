"""Visual Memory — Chloe помнит, что видела: скриншоты, экран телефона, свои картинки, фото из папок по просьбе.

«Покажи тот дизайн, что смотрели на прошлой неделе», «найди скриншот с ошибкой Google», «где картинка с кошкой?».
Каждая картинка: короткое описание по-русски (что на ней, какой текст виден), ключевые слова, когда, откуда
(скриншот экрана / телефона / картинка Chloe / папка), маленькая копия для галереи. Поиск — по словам описания и дате.
Описания делает модель, которая видит картинки (Qwen по Token Plan): картинка уходит к ней так же, как скриншоты
во время задач. Фото из своих папок — только по просьбе и после «да» (с числом файлов); приватные папки — никогда.
Маленькие копии скриншотов живут VISUAL_DAYS дней (настоящие скриншоты журнал хранит меньше); «забудь картинку» — сразу.
Таблицы vis_items и vis_fts в ~/.chloe/chloe.db.
"""
import base64
import hashlib
import io
import os
import pathlib
import re
import sqlite3
import threading
import time

from .config import DATA, JOURNAL_FILE

VISUAL_DAYS = int(os.environ.get("CHLOE_VISUAL_DAYS", "90"))
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
THUMB = 360
PER_RUN = 6                  # описаний за один проход: каждое — запрос к Qwen, пользователь ждать не должен
SOURCES = {"screen": "скриншот экрана", "phone": "экран телефона", "chloe": "картинка Chloe", "folder": "фото из папки"}
PROMPT = ("Опиши картинку для поиска по памяти. Ответь строго так:\n"
          "Описание: 1–2 предложения по-русски — что на ней (программа или сайт, люди, предметы, что происходит).\n"
          "Текст: главные слова, которые видны на картинке (названия, заголовки, ошибки), до 20 слов, как написано.\n"
          "Слова: 5–10 ключевых слов для поиска по-русски через запятую.")


class VisualError(Exception):
    pass


def thumb_of(data):
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.thumbnail((THUMB, THUMB))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def for_model(data, side=1024):
    """Картинка для модели — не больше 1024 по стороне, JPEG."""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def describe_image(data, hint=""):
    """Описание картинки моделью, которая видит изображения. (описание, текст, слова)."""
    from . import config
    from .thinking import openai_chat as oc

    jpeg = for_model(data)
    content = [{"type": "text", "text": PROMPT + ("\nОкно или источник: " + hint if hint else "")},
               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.standard_b64encode(jpeg).decode()}}]
    clients = oc.make_clients()
    model = config.MODEL_FAST if oc.PROVIDERS[oc.provider_of(config.MODEL_FAST)]["images"] else getattr(config, "MODEL_EYES", None) or config.MODEL_STRONG
    msg, _m = oc.chat(clients, [{"role": "user", "content": content}], model, tools=False, max_tokens=300)
    return parse_description(msg.content or "")


def parse_description(text):
    def field(name):
        m = re.search(r"^\s*{}\s*:\s*(.+)$".format(name), text, re.M | re.I)
        return m.group(1).strip() if m else ""
    desc = field("Описание") or text.strip().split("\n")[0][:300]
    return desc[:400], field("Текст")[:300], field("Слова")[:300]


def fts_query(text):
    from .knowledge import fts_query as q

    return q(text)


class Visual:
    def __init__(self, path=JOURNAL_FILE):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS vis_items (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL, ref TEXT NOT NULL UNIQUE, path TEXT, ts REAL, title TEXT,
            caption TEXT, seen_text TEXT, words TEXT, thumb BLOB, added REAL)""")
        self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS vis_fts USING fts5(caption, seen_text, words, title, "
                        "tokenize = 'unicode61 remove_diacritics 2')")
        self.db.commit()

    def has(self, ref):
        with self.lock:
            return self.db.execute("SELECT 1 FROM vis_items WHERE ref = ?", (ref,)).fetchone() is not None

    def add(self, source, ref, data, ts=None, title="", path=None, describe=describe_image):
        """Запомнить картинку: описание моделью + маленькая копия. Возвращает id (или старый, если уже есть)."""
        if self.has(ref):
            with self.lock:
                return self.db.execute("SELECT id FROM vis_items WHERE ref = ?", (ref,)).fetchone()[0]
        caption, seen, words = describe(data, title)
        thumb = thumb_of(data)
        with self.lock:
            cur = self.db.execute("INSERT INTO vis_items (source, ref, path, ts, title, caption, seen_text, words, thumb, added) "
                                  "VALUES (?,?,?,?,?,?,?,?,?,?)", (source, ref, str(path) if path else None, ts or time.time(),
                                                                   (title or "")[:200], caption, seen, words, thumb, time.time()))
            self.db.execute("INSERT INTO vis_fts (rowid, caption, seen_text, words, title) VALUES (?,?,?,?,?)",
                            (cur.lastrowid, caption, seen, words, title or ""))
            self.db.commit()
            return cur.lastrowid

    def get(self, vid, thumb=False):
        cols = "*" if thumb else "id, source, ref, path, ts, title, caption, seen_text, words, added"
        with self.lock:
            r = self.db.execute("SELECT {} FROM vis_items WHERE id = ?".format(cols), (vid,)).fetchone()
        return dict(r) if r else None

    def search(self, query="", since=None, until=None, source=None, limit=12):
        """Поиск по словам описания (и дате/источнику). Пустой запрос — последние."""
        cond, args = [], []
        if since:
            cond.append("v.ts >= ?")
            args.append(since)
        if until:
            cond.append("v.ts <= ?")
            args.append(until)
        if source:
            cond.append("v.source = ?")
            args.append(source)
        where = (" AND " + " AND ".join(cond)) if cond else ""
        cols = "v.id, v.source, v.ref, v.path, v.ts, v.title, v.caption, v.seen_text, v.words"
        with self.lock:
            q = fts_query(query) if query and query.strip() else ""
            if q:
                rows = self.db.execute("SELECT {} FROM vis_fts f JOIN vis_items v ON v.id = f.rowid WHERE vis_fts MATCH ?{} "
                                       "ORDER BY bm25(vis_fts), v.ts DESC LIMIT ?".format(cols, where), [q] + args + [limit]).fetchall()
            else:
                rows = self.db.execute("SELECT {} FROM vis_items v WHERE 1{} ORDER BY v.ts DESC LIMIT ?".format(cols, where),
                                       args + [limit]).fetchall()
        return [dict(r) for r in rows]

    def forget(self, vid):
        with self.lock:
            n = self.db.execute("DELETE FROM vis_items WHERE id = ?", (vid,)).rowcount
            self.db.execute("DELETE FROM vis_fts WHERE rowid = ?", (vid,))
            self.db.commit()
        return n > 0

    def prune(self, days=VISUAL_DAYS, now=None):
        """Копии скриншотов старше days — прочь (картинки Chloe и фото из папок — пока файл существует)."""
        limit = (now or time.time()) - days * 86400
        with self.lock:
            ids = [r[0] for r in self.db.execute("SELECT id FROM vis_items WHERE source IN ('screen', 'phone') AND ts < ?", (limit,))]
        for i in ids:
            self.forget(i)
        with self.lock:
            gone = [r[0] for r in self.db.execute("SELECT id, path FROM vis_items WHERE path IS NOT NULL") if not os.path.exists(r[1])]
        for i in gone:
            self.forget(i)
        return len(ids) + len(gone)

    def stats(self):
        with self.lock:
            return dict(self.db.execute("SELECT source, COUNT(*) FROM vis_items GROUP BY source").fetchall())

    def image_bytes(self, item):
        """Полная картинка, если она ещё есть (файл или скриншот журнала), иначе маленькая копия."""
        if item.get("path") and os.path.exists(item["path"]):
            return pathlib.Path(item["path"]).read_bytes()
        full = self.get(item["id"], thumb=True)
        return full["thumb"] if full else None


# --- что индексировать ---
def journal_screens(limit=200):
    """Скриншоты из журнала: (ref, source, путь, когда, подпись)."""
    from .journal import journal

    out = []
    with journal.lock:
        rows = journal.db.execute("SELECT id, ts, skill, title, screen FROM events WHERE screen IS NOT NULL ORDER BY id DESC LIMIT ?",
                                  (limit,)).fetchall()
    for r in rows:
        path = journal.screens / r["screen"]
        if path.exists():
            out.append(("journal:{}".format(r["id"]), "phone" if r["skill"] == "Телефон" or "phone" in (r["title"] or "") else "screen",
                        path, r["ts"], r["title"] or ""))
    return out


def chloe_images():
    from .qwen_media import IMAGE_DIR

    out = []
    if IMAGE_DIR.is_dir():
        for p in sorted(IMAGE_DIR.iterdir()):
            if p.suffix.lower() in IMAGE_EXT:
                out.append(("file:" + str(p), "chloe", p, p.stat().st_mtime, p.stem))
    return out


def folder_images(folder, limit=500):
    from .permissions import permissions

    root = pathlib.Path(os.path.expanduser(str(folder)))
    if not root.is_dir():
        raise VisualError("нет папки {}".format(root))
    if permissions.in_vault(str(root)):
        raise VisualError("это приватная папка (Private Vault)")
    out = []
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and not permissions.in_vault(os.path.join(dirpath, d))]
        for n in sorted(names):
            p = pathlib.Path(dirpath) / n
            if p.suffix.lower() in IMAGE_EXT and p.stat().st_size > 10_000:      # иконки и мелочь не нужны
                out.append(("file:" + str(p), "folder", p, p.stat().st_mtime, p.stem))
                if len(out) >= limit:
                    return out
    return out


def index(items, store, limit=PER_RUN, describe=describe_image, yield_to=None):
    """Описать и запомнить новые картинки. Возвращает (сколько добавлено, ошибки)."""
    added, errors = 0, []
    for ref, source, path, ts, title in items:
        if added >= limit:
            break
        if store.has(ref):
            continue
        if yield_to is not None and yield_to():          # пользователь заговорил — остальное в следующий раз
            break
        try:
            store.add(source, ref, pathlib.Path(path).read_bytes(), ts, title, path if source in ("chloe", "folder") else None, describe)
            added += 1
        except Exception as e:
            errors.append("{}: {}".format(pathlib.Path(path).name, str(e)[:80]))
            if len(errors) >= 3:
                break
    return added, errors


visual = Visual()


def background(stop=None, every=600):
    """Раз в 10 минут: новые скриншоты и картинки Chloe — в визуальную память (по 12 за раз), старое — прочь."""
    from .settings import settings
    from .signals import busy

    while not (stop and stop.is_set()):
        try:
            if not settings.get("safe_mode") and settings.get("visual_memory", True) and not busy.is_set():
                visual.prune()
                n, errs = index(journal_screens() + chloe_images(), visual, limit=PER_RUN, yield_to=busy.is_set)
                if n or errs:
                    print("[визуальная память: +{}{}]".format(n, ", ошибки: " + "; ".join(errs) if errs else ""))
        except Exception as e:
            print("[визуальная память: {}]".format(str(e)[:80]))
        (stop.wait(every) if stop else time.sleep(every))


def start():
    threading.Thread(target=background, daemon=True, name="visual").start()


def sha1(data):
    return hashlib.sha1(data).hexdigest()


VISUAL_DIR = DATA / "visual"
