"""Соцсети: контент-план, черновики постов, публикация.

Пишет посты мозг Chloe (это аргументы инструмента social), здесь — хранение и выпуск:
- Telegram-канал: публикует сама, от имени пользователя (Telethon, тот же вход, что и для чтения Telegram);
  только после «да» на конкретный текст, канал и время. Изменили пост — согласие нужно заново.
- Instagram, YouTube, TikTok: официальной публикации «от имени человека» у них нет без бизнес-аккаунтов и
  проверки приложения, поэтому Chloe собирает готовый пакет (подпись, хэштеги, картинка или ролик)
  в «Документы/Chloe/Посты», открывает папку и страницу загрузки — выкладывает пользователь сам.
Запланированный пост: в срок Telegram-пост уходит сам (если одобрен), для остальных Chloe напоминает и готовит пакет.
Таблица soc_posts в ~/.chloe/chloe.db.
"""
import json
import pathlib
import re
import shutil
import sqlite3
import threading
import time

from .config import JOURNAL_FILE, user_dir

NETWORKS = {"telegram": "Telegram", "instagram": "Instagram", "youtube": "YouTube", "tiktok": "TikTok"}
ALIASES = {"телеграм": "telegram", "телеграмм": "telegram", "tg": "telegram", "тг": "telegram", "инстаграм": "instagram",
           "инста": "instagram", "insta": "instagram", "ig": "instagram", "ютуб": "youtube", "yt": "youtube",
           "shorts": "youtube", "тикток": "tiktok", "тик ток": "tiktok"}
LIMITS = {"telegram": 4096, "instagram": 2200, "youtube": 5000, "tiktok": 2200}
CAPTION = 1024                     # Telegram: подпись под картинкой или видео короче обычного сообщения
UPLOAD = {"instagram": "https://www.instagram.com/", "youtube": "https://studio.youtube.com/",
          "tiktok": "https://www.tiktok.com/upload"}
EXPORT_DIR = user_dir("DOCUMENTS", "Documents") / "Chloe" / "Посты"
STATUS = {"draft": "черновик", "approved": "одобрен", "published": "опубликован", "exported": "пакет готов",
          "failed": "ошибка", "cancelled": "отменён"}
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".webm"}


class SocialError(Exception):
    pass


def network(name):
    n = (name or "").lower().strip()
    n = ALIASES.get(n, n)
    if n not in NETWORKS:
        raise SocialError("соцсеть: telegram, instagram, youtube или tiktok")
    return n


def check_media(paths):
    out = []
    for p in paths or []:
        f = pathlib.Path(str(p)).expanduser()
        if not f.is_file():
            raise SocialError("нет файла {}".format(f))
        from .permissions import permissions

        if permissions.in_vault(str(f)):
            raise SocialError("{} — в приватной папке (Private Vault), выкладывать её не буду".format(f.name))
        if f.suffix.lower() not in MEDIA_EXT:
            raise SocialError("{} — не картинка и не видео".format(f.name))
        out.append(str(f))
    return out


def check_text(net, text, media):
    if not text.strip() and not media:
        raise SocialError("пустой пост")
    limit = LIMITS[net]                  # длинная подпись в Telegram уходит отдельным сообщением под картинкой
    if len(text) > limit:
        raise SocialError("текст длиннее {} знаков — лимит {}".format(len(text), NETWORKS[net]))
    if net in ("youtube", "tiktok") and not any(m.lower().endswith((".mp4", ".mov", ".webm")) for m in media):
        raise SocialError("для {} нужен ролик (mp4)".format(NETWORKS[net]))
    if net == "instagram" and not media:
        raise SocialError("для Instagram нужна картинка или ролик")
    if net == "instagram" and len(re.findall(r"#\w+", text)) > 30:
        raise SocialError("в Instagram не больше 30 хэштегов")


class Social:
    def __init__(self, path):
        self.lock = threading.RLock()   # add() внутри замка читает пост через get()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS soc_posts (
            id INTEGER PRIMARY KEY, network TEXT NOT NULL, channel TEXT, title TEXT, text TEXT NOT NULL,
            media TEXT NOT NULL DEFAULT '[]', due REAL, status TEXT NOT NULL DEFAULT 'draft',
            created REAL, updated REAL, done_at REAL, result TEXT)""")
        self.db.commit()

    def _row(self, r):
        if not r:
            return None
        d = dict(r)
        d["media"] = json.loads(d["media"] or "[]")
        return d

    def add(self, net, text, title=None, channel=None, media=None, due=None):
        net = network(net)
        text = (text or "").strip()
        media = check_media(media)
        check_text(net, text, media)
        if net == "telegram" and not (channel or "").strip():
            raise SocialError("для Telegram нужен канал (channel) — название канала пользователя")
        now = time.time()
        with self.lock:
            cur = self.db.execute("INSERT INTO soc_posts (network, channel, title, text, media, due, created, updated) "
                                  "VALUES (?,?,?,?,?,?,?,?)", (net, (channel or "").strip() or None, (title or "").strip() or None,
                                                               text, json.dumps(media, ensure_ascii=False), due, now, now))
            self.db.commit()
            return self.get(cur.lastrowid)

    def get(self, pid):
        with self.lock:
            return self._row(self.db.execute("SELECT * FROM soc_posts WHERE id = ?", (pid,)).fetchone())

    def posts(self, include_done=False):
        q = "SELECT * FROM soc_posts" + ("" if include_done else " WHERE status IN ('draft', 'approved', 'failed', 'exported')")
        with self.lock:
            rows = self.db.execute(q + " ORDER BY coalesce(due, 9e18), id").fetchall()
        return [self._row(r) for r in rows]

    def update(self, pid, **fields):
        post = self.get(pid)
        if not post:
            raise SocialError("нет поста №{}".format(pid))
        if post["status"] == "published":
            raise SocialError("пост уже опубликован — менять его здесь поздно")
        new = dict(post)
        for k in ("text", "title", "channel"):
            if fields.get(k) is not None:
                new[k] = str(fields[k]).strip()
        if fields.get("network"):
            new["network"] = network(fields["network"])
        if fields.get("media") is not None:
            new["media"] = check_media(fields["media"])
        if "due" in fields:
            new["due"] = fields["due"]
        check_text(new["network"], new["text"], new["media"])
        changed = any(new[k] != post[k] for k in ("text", "title", "channel", "network", "media"))
        status = "draft" if changed and post["status"] in ("approved", "exported", "failed") else post["status"]
        with self.lock:
            self.db.execute("UPDATE soc_posts SET network=?, channel=?, title=?, text=?, media=?, due=?, status=?, updated=? "
                            "WHERE id=?", (new["network"], new["channel"], new["title"], new["text"],
                                           json.dumps(new["media"], ensure_ascii=False), new["due"], status, time.time(), pid))
            self.db.commit()
        return self.get(pid)

    def set_status(self, pid, status, result=None):
        with self.lock:
            self.db.execute("UPDATE soc_posts SET status=?, result=?, updated=?, done_at=? WHERE id=?",
                            (status, result, time.time(), time.time() if status in ("published", "cancelled") else None, pid))
            self.db.commit()
        return self.get(pid)

    def due_now(self, now=None):
        now = now or time.time()
        with self.lock:
            rows = self.db.execute("SELECT * FROM soc_posts WHERE due IS NOT NULL AND due <= ? "
                                   "AND status IN ('draft', 'approved')", (now,)).fetchall()
        return [self._row(r) for r in rows]


# --- выпуск ---
def slug(text):
    return "-".join(re.findall(r"\w+", (text or "").lower())[:5])[:40] or "пост"


def export(post, base=None):
    """Пакет для ручной публикации: подпись и медиа в отдельной папке. Возвращает путь к папке."""
    base = base or EXPORT_DIR
    folder = base / "{}-{}-{}".format(time.strftime("%Y%m%d"), post["network"], slug(post["title"] or post["text"]))
    folder.mkdir(parents=True, exist_ok=True)
    head = (post["title"] + "\n\n") if post["title"] and post["network"] == "youtube" else ""
    (folder / "подпись.txt").write_text(head + post["text"] + "\n", encoding="utf-8")
    for i, m in enumerate(post["media"], 1):
        src = pathlib.Path(m)
        if src.is_file():
            shutil.copy2(src, folder / "{:02d}{}".format(i, src.suffix.lower()))
    return folder


def publish_telegram(post, tg=None):
    """В канал пользователя: медиа с подписью (длинный текст — отдельным сообщением)."""
    from .tools.tg import find_chat

    if tg is None:
        from .telegram import telegram as tg
    if not tg.ready():
        raise SocialError("Telegram не подключён (python run.py --login-telegram)")
    chat, problem = find_chat(post["channel"])
    if problem:
        raise SocialError(problem)
    if chat["kind"] != "канал":
        raise SocialError("«{}» — не канал, а {}".format(chat["name"], chat["kind"]))
    text, media = post["text"], post["media"]

    async def go(client):
        if media:
            caption = text if len(text) <= CAPTION else ""
            await client.send_file(chat["id"], media if len(media) > 1 else media[0], caption=caption or None,
                                   supports_streaming=True)
            if text and not caption:
                await client.send_message(chat["id"], text)
        else:
            await client.send_message(chat["id"], text)

    tg.run(go, timeout=300)
    return chat["name"]


social = Social(JOURNAL_FILE)
