"""Настройки Chloe: пути, ключи, модели, голос, слова. Всё, что меняется переменными окружения CHLOE_*."""
import os
import pathlib
import platform
import subprocess
import sys


HOME = pathlib.Path.home()
# тесты без временной домашней папки испортили бы настоящие память, мозг и напоминания — отказываемся сразу
if "unittest" in sys.modules and os.environ.get("CHLOE_TEST_HOME") != str(HOME):
    raise RuntimeError("Тесты Chloe запускаются только так: .venv/bin/python -m unittest discover -s tests -t . "
                       "(иначе они работали бы с настоящей ~/.chloe)")
DATA = HOME / ".chloe"
DATA.mkdir(exist_ok=True)
try:
    os.chmod(DATA, 0o700)   # журнал, память и база — личные: другим пользователям компьютера не видны
except OSError:
    pass
for _stale in DATA.glob("tmp*.mp3"):   # озвучка, оставшаяся после прерванного запуска
    _stale.unlink(missing_ok=True)
BRAIN_FILE = DATA / "brain.json"
MEMORY_FILE = DATA / "memory.json"
JOURNAL_FILE = DATA / "chloe.db"
SETTINGS_FILE = DATA / "settings.json"   # что Chloe знает о месте пользователя: город и т.п.
BACKUPS_DIR = DATA / "backups"   # файлы, которые Chloe заменила: отмена возвращает их на место
UI_DIR = pathlib.Path(__file__).resolve().parent / "ui"   # страница мозга
OS_NAME = platform.system()  # Windows / Darwin / Linux
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

# Ключи — в отдельном файле только для владельца (права 600), а не в ~/.bashrc, который читают все программы.
# Строки вида NAME=значение (можно с export и кавычками). Ключ из файла главнее старой переменной окружения:
# терминал, открытый до смены ключа, не подсунет устаревший. Chloe этот файл не читает и не показывает.
KEYS_DIR = HOME / ".config" / "chloe"
KEYS_FILE = KEYS_DIR / "keys.env"
KEY_NAMES = ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "QWEN_BASE_URL", "DEEPSEEK_API_KEY",
             "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "HA_URL", "HA_TOKEN")


def parse_keys(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if value[:1] in ("\"", "'"):             # "ключ"   # комментарий — берём только то, что в кавычках
            end = value.find(value[0], 1)
            value = value[1:end] if end > 0 else ""
        else:
            value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()
        if sep and name in KEY_NAMES and value:
            out[name] = value
    return out


def load_keys(path=KEYS_FILE):
    """Ключи из защищённого файла — в окружение (клиенты API берут их оттуда). Возвращает имена загруженных."""
    try:
        if os.name == "posix" and path.stat().st_mode & 0o077:
            path.chmod(0o600)   # файл с ключами видит только владелец
        keys = parse_keys(path.read_text(encoding="utf-8"))
    except OSError:
        return []
    os.environ.update(keys)
    return sorted(keys)


load_keys()


def user_dir(xdg_name, default):
    """Папка пользователя. На Linux берётся из xdg-user-dir: там она может называться «Загрузки»."""
    if OS_NAME == "Linux":
        try:
            out = subprocess.run(["xdg-user-dir", xdg_name], capture_output=True, text=True, timeout=3).stdout.strip()
            if out and pathlib.Path(out) != HOME:
                return pathlib.Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    return HOME / default


DOWNLOADS = user_dir("DOWNLOAD", "Downloads")
DESKTOP = user_dir("DESKTOP", "Desktop")
DOCUMENTS = user_dir("DOCUMENTS", "Documents")

GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
GEMINI_THINKING = os.environ.get("CHLOE_THINKING", "low")   # minimal / low / medium / high — чем меньше, тем быстрее
# Qwen (Alibaba, QwenCloud) и DeepSeek — через их OpenAI-совместимые API, см. thinking/openai_chat.py
QWEN_KEY = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY")
# кто думает: если не задано явно — Qwen, потом DeepSeek (у кого есть ключ), потом Claude, потом Gemini
PROVIDER = os.environ.get("CHLOE_PROVIDER") or (
    "qwen" if QWEN_KEY else "deepseek" if DEEPSEEK_KEY else
    "anthropic" if os.environ.get("ANTHROPIC_API_KEY") or not GEMINI_KEY else "gemini")
# два мозга: быстрый для простых просьб, сильный для сложных (экран, файлы, много шагов) — см. thinking/router.py.
# CHLOE_MODEL задаёт одну модель на всё (без переключения). «+thinking» — та же модель, но с раздумьями.
FAST_DEFAULT = {"qwen": "qwen3.8-flash", "deepseek": "deepseek-flash",
                "gemini": "gemini-3.5-flash-lite", "anthropic": "claude-haiku-5-5"}
STRONG_DEFAULT = {"qwen": "qwen3.8-flash+thinking", "deepseek": "deepseek-v4-pro",
                  "gemini": "gemini-3.5-flash", "anthropic": "claude-sonnet-5-5"}
MODEL_FAST = os.environ.get("CHLOE_MODEL_FAST") or os.environ.get("CHLOE_MODEL") or FAST_DEFAULT.get(PROVIDER)
OPENAI_STYLE = {"qwen", "deepseek"}   # провайдеры, которые думают через thinking/openai_chat.py
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
# Qwen/DeepSeek + ключ Claude: быстрый мозг — DeepSeek/Qwen, сильный — Claude Haiku 5.5 (видит экран, быстрый
# и дешёвый; выбор пользователя). Sonnet — CHLOE_MODEL_STRONG=claude-sonnet-5-5. Claude ещё и подстраховывает.
MIXED_STRONG = "claude-haiku-5-5" if PROVIDER in OPENAI_STYLE and ANTHROPIC_KEY else None
MODEL_STRONG = (os.environ.get("CHLOE_MODEL_STRONG") or os.environ.get("CHLOE_MODEL")
                or MIXED_STRONG or STRONG_DEFAULT.get(PROVIDER))
# «глаза»: быстрый мозг не видит экран (DeepSeek), а есть Claude — экран смотрит Claude Haiku (быстро и дёшево),
# а Sonnet подключается, если Haiku ошибся, задача затянулась или нужны команды, файлы, тексты
MODEL_EYES = (os.environ.get("CHLOE_MODEL_EYES") or
              ("claude-haiku-5-5" if PROVIDER == "deepseek" and ANTHROPIC_KEY and not os.environ.get("CHLOE_MODEL") else None))
if MODEL_EYES == MODEL_STRONG:
    MODEL_EYES = None   # сильный мозг и так Haiku — отдельные «глаза» не нужны


def has_key(provider=None):
    provider = provider or PROVIDER
    return bool({"qwen": QWEN_KEY, "deepseek": DEEPSEEK_KEY, "gemini": GEMINI_KEY,
                 "anthropic": ANTHROPIC_KEY}.get(provider))


LANG = os.environ.get("CHLOE_LANG", "ru-RU")                     # для узбекского: uz-UZ
VOICE = os.environ.get("CHLOE_VOICE", "ru-RU-SvetlanaNeural")    # голос edge-tts: Светлана (русский, Microsoft)
VOICES = [VOICE]   # если Светлана не отвечает, Chloe говорит офлайн-голосом Piper (тоже женским), а не мужским Дмитрием
TTS = os.environ.get("CHLOE_TTS", "edge")                         # edge — Светлана (Microsoft, онлайн); piper — офлайн и быстрее; svetlana — только Светлана, без запасных; qwen — голос Qwen (запасной — Светлана)
# слух: qwen (по умолчанию) — точнее: понимает подсказку о разговоре, английские названия, тихую речь; 2–4,5 с,
# спрашивается вместе с Google (ждём его не дольше CHLOE_QWEN_ASR_WAIT), Google — запасной и сверка конца фразы;
# google — только Google, быстрее (0,6–1,5 с), но грубее.
ASR = os.environ.get("CHLOE_ASR", "qwen")
PIPER_VOICE = os.environ.get("CHLOE_PIPER_VOICE", "ru_RU-irina-medium")   # русские: irina (жен.), denis, dmitri, ruslan
VOICES_DIR = DATA / "voices"                                       # модели Piper
EARS_DIR = DATA / "ears"                                           # офлайн-слух Vosk: слово «Хлоя» без интернета
EARS_MODEL = os.environ.get("CHLOE_EARS_MODEL", "vosk-model-small-ru-0.22")
WAKE_OFFLINE = os.environ.get("CHLOE_WAKE", "offline") != "cloud"   # cloud — как раньше: вся речь в Google
CONFIRM = os.environ.get("CHLOE_CONFIRM", "safe")                # safe — спрашивать перед необратимым; off — не спрашивать
KEEP_SCREENS = int(os.environ.get("CHLOE_KEEP_SCREENS", "7"))    # сколько дней хранить скриншоты в журнале; 0 — не хранить
WAKE_WORDS = ("хлоя", "хлои", "хлое", "хлою", "хлоей", "хлоэ", "хлоё", "клоя", "клои", "клое", "клою", "клоэ", "флоэ", "флоя",
              "chloe", "chloé")   # только целые слова; похожие (одна буква не та) — см. ears.is_wake_word
STOP_WORDS = ("стоп", "хватит", "отмена", "замолчи", "stop")
EXIT_WORDS = ("выключись", "до свидания", "выход")
OVERHEAR = os.environ.get("CHLOE_OVERHEAR", "on") != "off"      # записывать речь в комнате (офлайн, только на этом компьютере)
OVERHEAR_DAYS = int(os.environ.get("CHLOE_OVERHEAR_DAYS", "7"))  # сколько дней её хранить
ACTIVE_WINDOW = int(os.environ.get("CHLOE_ACTIVE", "45"))   # сколько секунд после ответа можно говорить без слова «Хлоя»
PAUSE = float(os.environ.get("CHLOE_PAUSE", "1.5"))          # пауза в секундах, после которой фраза считается законченной
PHRASE_LIMIT = int(os.environ.get("CHLOE_PHRASE", "40"))     # самая длинная фраза в секундах
YES_WORDS = {"да", "ага", "давай", "подтверждаю", "конечно", "yes", "ок", "окей", "ok", "okay"}
NO_WORDS = {"нет", "не", "отмена", "отменить", "стоп", "no"}
EXECUTABLE_EXT = (".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".dmg", ".pkg", ".app", ".deb", ".rpm", ".appimage", ".jar", ".scr",
                  ".com", ".cpl", ".msc", ".hta", ".lnk", ".reg", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".py", ".pyw",
                  ".desktop", ".command", ".run", ".bin")
