"""Connector Layer — все подключения Chloe к внешнему миру в одном реестре.

У каждого подключения: что это и что через него можно, статус (работает / не подключено / сломано), какие инструменты
через него ходят, когда и сколько ими пользовались (из журнала), проверка вживую, выключение одной фразой или кнопкой
и, где это возможно, «забыть» — выйти из аккаунта и стереть вход.
Выключенное подключение не трогает ваши данные и ключи: его инструменты просто закрыты (как безопасный режим, но точечно).
Основа (мозг, голос, слух) выключить нельзя — без неё Chloe не работает; её можно только смотреть и проверять.
Новое подключение (Home Assistant, очки) добавляется сюда одной записью — мозгу Chloe ничего менять не нужно.
"""
import json
import shutil
import subprocess
import time

from . import config
from .settings import settings

CORE = "core"


class Connector:
    def __init__(self, cid, name, what, tools=(), kind="service", status=None, check=None, forget=None, connect_hint="",
                 data=""):
        self.id, self.name, self.what, self.tools, self.kind = cid, name, what, set(tools), kind
        self._status, self._check, self._forget, self.connect_hint, self.data = status, check, forget, connect_hint, data

    def status(self):
        """(level, detail): level — ok / off / fail / planned."""
        if self.kind == "planned":
            return "planned", "ещё не подключено — в плане"
        try:
            return self._status() if self._status else ("ok", "")
        except Exception as e:
            return "fail", "не проверилось: {}".format(type(e).__name__)

    def check(self):
        if self._check is None:
            return self.status()
        try:
            return self._check()
        except Exception as e:
            return "fail", "{}: {}".format(type(e).__name__, str(e)[:120])

    @property
    def can_forget(self):
        return self._forget is not None

    def forget(self):
        return self._forget()


# --- состояния подключений ---
def _calendar_status():
    from . import google_calendar as gc

    if gc.connected():
        return "ok", "вход выполнен, доступ только к событиям"
    if gc.client():
        return "off", "файл клиента есть, вход не выполнен — «подключи календарь»"
    return "off", "нет OAuth-клиента Google"


def _calendar_check():
    from .system_state import ping_calendar

    x = ping_calendar()
    return x["level"], x["detail"]


def _calendar_forget():
    from . import google_calendar as gc

    return "доступ к календарю отозван у Google, токен удалён" if gc.sign_out() else "календарь и так не был подключён"


def _tg_status():
    from .telegram import telegram

    return ("ok", "вход выполнен (ваш аккаунт)") if telegram.ready() else ("off", "не подключён — python run.py --login-telegram")


def _tg_check():
    from .system_state import ping_telegram

    x = ping_telegram()
    return x["level"], x["detail"]


def _tg_forget():
    from .config import DATA
    from .telegram import telegram

    async def out(client):
        await client.log_out()                     # сессия закрывается и в списке устройств Telegram

    try:
        if telegram.ready():
            telegram.run(out, timeout=20)
    except Exception:
        pass
    gone = [p.name for p in (DATA / "telegram.session", DATA / "telegram.json") if p.exists()]
    for p in (DATA / "telegram.session", DATA / "telegram.json"):
        p.unlink(missing_ok=True)
    telegram.client = None
    return "вышла из Telegram, вход стёрт ({})".format(", ".join(gone) or "файлов не было")


def _phone_status():
    if not shutil.which("adb"):
        return "off", "adb не установлен"
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=3).stdout
    ready = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]
    return ("ok", "подключён ({})".format(", ".join(ready))) if ready else ("off", "не подключён (кабель или «Отладка по Wi-Fi»)")


def _phone_check():
    from .system_state import ping_phone

    x = ping_phone()
    return x["level"], x["detail"]


def _qwen_status():
    if not config.QWEN_KEY:
        return "off", "нет ключа"
    from . import qwen_plan

    if qwen_plan.exhausted():
        return "fail", "кредиты Token Plan закончились — отвечаю запасной моделью"
    return "ok", "ключ есть ({})".format("Token Plan" if config.QWEN_KEY.startswith("sk-sp-") else "оплата по факту")


def _brain_check(name):
    def go():
        from .system_state import ping_brains

        for x in ping_brains():
            if x["name"] == name:
                return x["level"], x["detail"]
        return "off", "нет ключа"
    return go


def _key_status(key, label):
    return lambda: ("ok", "ключ есть") if getattr(config, key) else ("off", "нет ключа {}".format(label))


def _bl_status():
    if not shutil.which("bl"):
        return "off", "Bailian CLI не установлен"
    out = subprocess.run(["bl", "auth", "status"], capture_output=True, text=True, timeout=10).stdout
    return ("ok", "вход в консоль Alibaba выполнен") if "Console gateway:  config" in out or "Console gateway: config" in out \
        else ("off", "вход не выполнен — bl auth login --console --console-site international")


def _bl_forget():
    r = subprocess.run(["bl", "auth", "logout", "--console"], capture_output=True, text=True, timeout=20)
    return "вышла из консоли Alibaba в Bailian CLI" if r.returncode == 0 else "не получилось: " + (r.stderr or r.stdout).strip()[:120]


def _voice_status():
    return "ok", {"edge": "Светлана (Microsoft, онлайн)", "piper": "Ирина (офлайн)", "qwen": "голос Qwen"}.get(config.TTS, config.TTS)


def _voice_check():
    from .system_state import ping_voice

    x = ping_voice()
    return x["level"], x["detail"]


def _ha_status():
    from .home import status_text

    return status_text()


def _remote_status():
    from .config import DATA

    return ("ok", "телефон-пульт в домашней Wi-Fi (по коду)") if (DATA / "remote").exists() else ("off", "не настроен")


def _internet_check():
    from .system_state import ping_internet

    x = ping_internet()
    return x["level"], x["detail"]


REGISTRY = [
    Connector("google_calendar", "Google Calendar", "смотреть, добавлять и удалять события вашего календаря", {"calendar"},
              status=_calendar_status, check=_calendar_check, forget=_calendar_forget,
              connect_hint="«Хлоя, подключи календарь» — вход через Google в браузере", data="токен — ~/.config/chloe/google_token.json"),
    Connector("telegram", "Telegram", "читать чаты и отправлять сообщения от вашего имени, публиковать в ваши каналы",
              {"tg_read", "tg_unread", "tg_send", "social"}, status=_tg_status, check=_tg_check, forget=_tg_forget,
              connect_hint="python run.py --login-telegram", data="сессия — ~/.chloe/telegram.session"),
    Connector("phone", "Телефон Android", "экран, нажатия, приложения, ссылки и текст на телефоне (adb)", {"phone"},
              status=_phone_status, check=_phone_check, connect_hint="кабель или «Отладка по Wi-Fi»"),
    Connector("internet", "Интернет", "поиск, страницы, новости, мир, погода, скачивание, YouTube",
              {"web_search", "read_web_page", "news", "world", "weather", "download_file", "play_youtube", "open_url", "morning_brief"},
              check=_internet_check),
    Connector("qwen_media", "Qwen: картинки, видео, ролики", "рисовать, делать видео и ролики (кредиты Token Plan)",
              {"create_media", "make_film"}, status=_qwen_status),
    Connector("bailian_cli", "Bailian CLI (консоль Alibaba)", "точный остаток кредитов Qwen", {"qwen_credits"},
              status=_bl_status, forget=_bl_forget, connect_hint="bl auth login --console --console-site international",
              data="вход — ~/.bailian/config.json"),
    Connector("remote", "Телефон-пульт", "говорить с Хлоей и смотреть её мозг с телефона в домашней Wi-Fi", set(),
              status=_remote_status, connect_hint="окно Хлои → «Телефон» → QR-код"),
    Connector("qwen", "Мозг Qwen", "основной быстрый мозг, голос и слух Qwen", kind=CORE, status=_qwen_status, check=_brain_check("Qwen")),
    Connector("claude", "Мозг Claude", "сильный мозг для сложных задач и экрана", kind=CORE,
              status=_key_status("ANTHROPIC_KEY", "ANTHROPIC_API_KEY"), check=_brain_check("Claude")),
    Connector("deepseek", "Мозг DeepSeek", "запасной мозг", kind=CORE, status=_key_status("DEEPSEEK_KEY", "DEEPSEEK_API_KEY"),
              check=_brain_check("DeepSeek")),
    Connector("voice", "Голос", "как Хлоя говорит", kind=CORE, status=_voice_status, check=_voice_check),
    Connector("home_assistant", "Home Assistant", "умный дом и офис: комнаты, свет, климат, датчики, сцены (важное — с вопросом)",
              {"home"}, status=_ha_status, connect_hint="HA_URL и HA_TOKEN (долгосрочный токен) в ~/.config/chloe/keys.env",
              data="токен — ~/.config/chloe/keys.env"),
    Connector("glasses", "Rokid Glasses", "умные очки: экран перед глазами, камера, голос — через Android-приложение на телефоне "
              "(Rokid CXR-M SDK)", kind="planned"),
]
BY_ID = {c.id: c for c in REGISTRY}
ALIASES = {"календарь": "google_calendar", "гугл календарь": "google_calendar", "calendar": "google_calendar",
           "телеграм": "telegram", "телеграмм": "telegram", "телефон": "phone", "андроид": "phone", "интернет": "internet",
           "сеть": "internet", "картинки": "qwen_media", "видео": "qwen_media", "bailian": "bailian_cli", "бэйлянь": "bailian_cli",
           "пульт": "remote", "умный дом": "home_assistant", "очки": "glasses"}


def find(name):
    n = (name or "").lower().strip()
    if n in BY_ID:
        return BY_ID[n]
    n = ALIASES.get(n, n)
    if n in BY_ID:
        return BY_ID[n]
    return next((c for c in REGISTRY if n and (n in c.name.lower() or n in c.id)), None)


def disabled():
    return set(settings.get("connectors_off") or [])


def is_on(cid):
    return cid not in disabled()


def set_on(cid, on):
    c = BY_ID.get(cid)
    if not c or c.kind in (CORE, "planned"):
        return False
    off = disabled()
    (off.discard if on else off.add)(cid)
    settings.set("connectors_off", sorted(off))
    try:
        from .journal import journal

        journal.add("brain", "Подключения", "{} — {}".format(c.name, "включено" if on else "выключено"), {"connector": cid})
    except Exception:
        pass
    return True


def blocks(tool):
    """Причина запрета, если инструмент ходит через выключенное подключение."""
    for cid in disabled():
        c = BY_ID.get(cid)
        if c and tool in c.tools:
            return "подключение «{}» выключено; включить — «включи {}»".format(c.name, c.name.split(" (")[0].lower())
    return None


def usage(days=7, now=None):
    """{id: {"count", "last"}} — сколько и когда пользовались инструментами подключения."""
    from .journal import journal

    since = (now or time.time()) - days * 86400
    by_tool = {}
    with journal.lock:
        for ts, detail in journal.db.execute("SELECT ts, detail FROM events WHERE kind = 'tool' AND ts > ?", (since,)):
            try:
                d = json.loads(detail or "{}")
                d = json.loads(d) if isinstance(d, str) else d
                tool = d.get("tool")
            except ValueError:
                continue
            u = by_tool.setdefault(tool, [0, 0])
            u[0] += 1
            u[1] = max(u[1], ts)
    out = {}
    for c in REGISTRY:
        count = sum(by_tool.get(t, [0, 0])[0] for t in c.tools)
        last = max([by_tool.get(t, [0, 0])[1] for t in c.tools] or [0])
        out[c.id] = {"count": count, "last": last or None}
    return out


def overview(deep=False):
    import concurrent.futures

    use = usage()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(REGISTRY)) as pool:   # проверки параллельно: секунды, а не десятки
        states = list(pool.map(lambda c: c.check() if deep and c.kind != "planned" else c.status(), REGISTRY))
    rows = []
    for c, (level, detail) in zip(REGISTRY, states):
        if c.kind not in (CORE, "planned") and not is_on(c.id):
            level, detail = "paused", "выключено вами — " + detail
        rows.append({"id": c.id, "name": c.name, "what": c.what, "kind": c.kind, "level": level, "detail": detail,
                     "tools": sorted(c.tools), "can_off": c.kind not in (CORE, "planned"), "can_forget": c.can_forget,
                     "on": is_on(c.id), "hint": c.connect_hint, "data": c.data, "uses": use[c.id]["count"], "last": use[c.id]["last"]})
    return rows
