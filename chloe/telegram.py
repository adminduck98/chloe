"""Telegram от имени пользователя (Telethon — тот же протокол, что у Telegram Desktop).

Вход один раз и только сам пользователь: python run.py --login-telegram — спросит api_id и api_hash
(my.telegram.org → API development tools), номер телефона и код из Telegram. Chloe этих данных не видит:
сессия хранится в ~/.chloe/telegram.session (только для владельца), ключи — в ~/.chloe/telegram.json.

Читать — без вопросов; отправить — только после «да» с повтором получателя и текста.
Прочитанное Chloe не отмечается прочитанным: у вас в Telegram всё останется как было.
"""
import asyncio
import json
import os
import threading

from .config import DATA

SESSION = DATA / "telegram"            # Telethon допишет .session
KEYS_FILE = DATA / "telegram.json"


def keys():
    """(api_id, api_hash) из переменных окружения или ~/.chloe/telegram.json; None — не настроено."""
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if not (api_id and api_hash) and KEYS_FILE.exists():
        try:
            data = json.loads(KEYS_FILE.read_text())
            api_id, api_hash = data.get("api_id"), data.get("api_hash")
        except (OSError, ValueError):
            pass
    return (int(api_id), str(api_hash)) if api_id and api_hash else None


def private(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class Telegram:
    """Свой цикл asyncio в отдельном потоке: инструменты Chloe вызывают его синхронно."""

    def __init__(self):
        self.client = None
        self.loop = None
        self.lock = threading.Lock()

    def ready(self):
        return keys() is not None and SESSION.with_suffix(".session").exists()

    def _start(self):
        with self.lock:
            if self.client is not None:
                return self.client
            from telethon import TelegramClient

            self.loop = asyncio.new_event_loop()
            threading.Thread(target=self.loop.run_forever, daemon=True, name="telegram").start()
            api_id, api_hash = keys()

            async def connect():
                client = TelegramClient(str(SESSION), api_id, api_hash, device_model="Chloe", app_version="1.0")
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    raise RuntimeError("вход в Telegram устарел — пусть пользователь снова запустит python run.py --login-telegram")
                return client

            self.client = asyncio.run_coroutine_threadsafe(connect(), self.loop).result(30)
            private(SESSION.with_suffix(".session"))
            return self.client

    def run(self, coro_fn, timeout=30):
        client = self._start()
        return asyncio.run_coroutine_threadsafe(coro_fn(client), self.loop).result(timeout)

    # --- то, что нужно инструментам ---
    def dialogs(self, limit=200):
        """[{id, name, unread, kind}] — чаты по порядку, как в Telegram."""
        async def go(client):
            out = []
            async for d in client.iter_dialogs(limit=limit):
                kind = "канал" if d.is_channel and not d.is_group else "группа" if d.is_group else "личный"
                out.append({"id": d.id, "name": d.name or "", "unread": d.unread_count, "kind": kind,
                            "muted": bool(getattr(d.dialog.notify_settings, "mute_until", None))})
            return out
        return self.run(go)

    def messages(self, chat_id, count=10):
        """[{me, sender, text, time}] — от старых к новым."""
        async def go(client):
            out = []
            async for m in client.iter_messages(chat_id, limit=count):
                sender = "я" if m.out else (getattr(m.sender, "first_name", None) or getattr(m.sender, "title", None) or "")
                text = m.message or ("[" + type(m.media).__name__.replace("MessageMedia", "").lower() + "]" if m.media else "")
                out.append({"me": m.out, "sender": sender, "text": text, "time": m.date.astimezone().strftime("%d.%m %H:%M")})
            return list(reversed(out))
        return self.run(go)

    def send(self, chat_id, text):
        async def go(client):
            await client.send_message(chat_id, text)
        self.run(go)


telegram = Telegram()


def login():
    """Вход в Telegram в терминале. Номер телефона и код вводит сам пользователь."""
    k = keys()
    if k is None:
        print("Нужны api_id и api_hash: откройте https://my.telegram.org → API development tools → создайте приложение.")
        api_id = input("api_id: ").strip()
        api_hash = input("api_hash: ").strip()
        if not api_id.isdigit() or len(api_hash) < 20:
            print("Похоже на опечатку: api_id — число, api_hash — длинная строка из букв и цифр.")
            return
        KEYS_FILE.write_text(json.dumps({"api_id": int(api_id), "api_hash": api_hash}))
        private(KEYS_FILE)
        k = (int(api_id), api_hash)
    from telethon.sync import TelegramClient

    with TelegramClient(str(SESSION), k[0], k[1], device_model="Chloe", app_version="1.0") as client:
        me = client.get_me()
        print("Готово: Chloe вошла в Telegram как", me.first_name, "— в списке устройств она называется «Chloe».")
    private(SESSION.with_suffix(".session"))
