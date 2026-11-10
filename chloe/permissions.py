"""Карта прав доступа (DATA PERMISSION MAP) и Private Vault: что Chloe может видеть и делать — решает пользователь.

Категория — группа данных или действий (экран, файлы, Telegram…), у каждой уровень:
    allow — разрешено (свои подтверждения инструментов, например «удалить?», остаются);
    ask   — спрашивать каждый раз;
    block — запрещено.
Private Vault — приватные папки: внутрь Chloe не заглядывает совсем (не читает, не ищет, не изучает,
не меняет, окна с ними на экране не смотрит, изученные оттуда документы в ответах не участвуют).

Ослабить защиту (разрешить, убрать папку из Vault) голосом можно только после «да, делай»: так команда,
вычитанная со страницы или из документа, не откроет себе доступ. Усилить — сразу.
Проверка — в одном месте: tools.run_tool зовёт check() перед каждым действием модели.
Хранится в ~/.chloe/permissions.json.
"""
import json
import pathlib
import re
import threading

from .config import DATA, HOME, KEYS_DIR

BAILIAN_DIR = HOME / ".bailian"

FILE = DATA / "permissions.json"
# команда, которая может показать ключи: файл с ними, копии ~/.bashrc, переменные окружения
SECRET_HINTS = re.compile(r"keys\.env|\.config/chloe|\.bashrc\.bak|\.bailian|\bbl\s+(?:auth|config)\b|_API_KEY|\bprintenv\b|\benv\b|/environ\b|\bdeclare\s+-x|\bexport\s+-p", re.I)
LEVELS = ("allow", "ask", "block")
LEVEL_RU = {"allow": "разрешено", "ask": "спрашивать", "block": "запрещено"}
STRICT = {"allow": 0, "ask": 1, "block": 2}

# ключ: (название, что входит, инструменты, уровень по умолчанию — как Chloe работала до карты прав)
CATEGORIES = {
    "screen":       ("Экран", "скриншоты и постоянное зрение", {"screenshot", "vision"}, "allow"),
    "files_read":   ("Файлы: чтение", "читать, искать, открывать файлы и папки", {"read_text_file", "list_folder", "search_files", "open_path", "transcribe_audio"}, "allow"),
    "files_change": ("Файлы: изменение", "создавать, менять, перемещать, удалять", {"write_text_file", "create_folder", "move_path", "copy_path", "delete_path", "undo_change"}, "allow"),
    "commands":     ("Команды", "команды терминала", {"run_command"}, "allow"),
    "control":      ("Мышь и клавиатура", "клики, печать, клавиши, окна, буфер обмена", {"mouse_click", "type_text", "press_keys", "scroll", "window", "clipboard"}, "allow"),
    "internet":     ("Интернет", "поиск, сайты, YouTube, скачивание", {"web_search", "read_web_page", "open_url", "play_youtube", "download_file", "weather"}, "allow"),
    "telegram":     ("Telegram", "читать и отправлять сообщения", {"tg_read", "tg_unread", "tg_send"}, "allow"),
    "phone":        ("Телефон", "экран, нажатия, приложения и ссылки на телефоне Android", {"phone"}, "allow"),
    "calendar":     ("Календарь Google", "смотреть, добавлять и удалять события (добавление и удаление — с подтверждением)", {"calendar"}, "allow"),
    "media":        ("Картинки и видео", "рисовать картинки и делать видео через Qwen (видео и ролики — с подтверждением)", {"create_media", "make_film"}, "allow"),
    "voice_studio": ("Озвучка", "озвучивать тексты и документы в mp3 (аудиокниги)", {"narrate"}, "allow"),
    "news":         ("Новости", "читать свежие новости из открытых лент и утреннюю сводку", {"news", "morning_brief", "world"}, "allow"),
    "finance":      ("Финансы", "список подписок и платежей пользователя (к банку не подключается)", {"subscriptions"}, "allow"),
    "social":       ("Соцсети", "контент-план и посты; публикация в Telegram-канал — только после «да»", {"social"}, "allow"),
    "memory":       ("Память", "запоминать, забывать, история разговоров", {"remember", "forget", "conversation_log", "sleep_now"}, "allow"),
    "knowledge":    ("База знаний", "изучать документы и отвечать по ним", {"learn_document", "ask_knowledge", "list_knowledge", "forget_document", "knowledge_map"}, "allow"),
    "projects":     ("Проекты", "задачи, решения и состояние проектов (git, GitHub)", {"projects", "project_overview", "project_task", "project_note"}, "allow"),
    "power":        ("Питание", "выключение, перезагрузка, сон, блокировка", {"power"}, "allow"),   # выключение и так спрашивает
}
TOOL_CATEGORY = {t: key for key, (_, _, tools, _) in CATEGORIES.items() for t in tools}
PATH_ARGS = ("path", "src", "dst", "folder", "source", "target", "destination", "image")


class Permissions:
    def __init__(self, path=FILE):
        self.path = pathlib.Path(path)
        self.lock = threading.Lock()
        self.levels, self.vault = {}, []
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        levels = data.get("levels") or {}
        self.levels = {k: levels.get(k) if levels.get(k) in LEVELS else default for k, (_, _, _, default) in CATEGORIES.items()}
        self.vault = [str(p) for p in data.get("vault", []) if p]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"levels": self.levels, "vault": self.vault}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # --- уровни ---
    def level(self, key):
        return self.levels.get(key, "allow")

    def set_level(self, key, level):
        if key not in CATEGORIES or level not in LEVELS:
            raise ValueError("Нет такой категории или уровня: {} {}".format(key, level))
        with self.lock:
            self.levels[key] = level
            self.save()

    def loosens(self, key, level):
        """Ослабляет ли это защиту (нужен голосовой «да»)."""
        return STRICT[level] < STRICT[self.level(key)]

    # --- Private Vault ---
    @staticmethod
    def _norm(path):
        p = pathlib.Path(str(path)).expanduser()
        if not p.is_absolute():
            p = HOME / p
        try:
            return p.resolve()
        except OSError:
            return p

    def vault_add(self, path):
        p = str(self._norm(path))
        with self.lock:
            if p not in self.vault:
                self.vault.append(p)
                self.save()
        return p

    def vault_remove(self, path):
        p = str(self._norm(path))
        with self.lock:
            if p in self.vault:
                self.vault.remove(p)
                self.save()
                return True
        return False

    @classmethod
    def locked(cls, path):
        """Файл с ключами, копии ~/.bashrc со старыми ключами и вход Bailian CLI (~/.bailian: ключ и токен консоли
        Alibaba) закрыты всегда — карта прав их не открывает."""
        p = cls._norm(path)
        for d in (cls._norm(KEYS_DIR), cls._norm(BAILIAN_DIR)):
            if p == d or d in p.parents:
                return True
        return p.name.startswith(".bashrc.bak")

    def in_vault(self, path):
        if path and self.locked(path):
            return True
        if not self.vault or not path:
            return False
        p = self._norm(path)
        for v in self.vault:
            vp = pathlib.Path(v)
            if p == vp or vp in p.parents:
                return True
        return False

    def mentions_vault(self, text):
        """Путь к приватной папке внутри текста команды: `cat ~/Личное/паспорт.pdf`."""
        t = str(text or "").replace("~", str(HOME))
        if SECRET_HINTS.search(t):
            return True   # ключи: файл с ними, копии ~/.bashrc, переменные окружения
        if not self.vault or not text:
            return False
        return any(v in t for v in self.vault)

    def vault_names(self):
        """Имена приватных папок — окна с ними в заголовке Chloe не смотрит."""
        return [pathlib.Path(v).name for v in self.vault if pathlib.Path(v).name] + ["keys.env"]

    # --- проверка перед действием ---
    def check(self, tool, args):
        """None — можно; ("block", причина) — нельзя; ("ask", вопрос) — сначала спросить."""
        args = args if isinstance(args, dict) else {}
        for k in PATH_ARGS:
            if isinstance(args.get(k), str) and self.in_vault(args[k]):
                return "block", "это приватная папка (Private Vault): туда я не заглядываю"
        if tool == "run_command" and SECRET_HINTS.search(str(args.get("command", ""))):
            return "block", "команда касается ключей API — их я не читаю и не показываю"
        if tool == "run_command" and self.mentions_vault(args.get("command", "")):
            return "block", "команда касается приватной папки (Private Vault)"
        key = TOOL_CATEGORY.get(tool)
        if not key:
            return None
        title = CATEGORIES[key][0]
        level = self.level(key)
        if level == "block":
            return "block", "доступ «{}» запрещён в карте прав".format(title)
        if level == "ask":
            return "ask", "Разрешить доступ «{}» ({})?".format(title, tool)
        return None

    def screen_allowed(self):
        return self.level("screen") == "allow"

    # --- карта для окна и голоса ---
    def map(self, usage=None):
        usage = usage or {}
        return {"categories": [{"key": k, "title": t, "desc": d, "level": self.level(k), "level_ru": LEVEL_RU[self.level(k)],
                                "uses": usage.get(k, {}).get("uses", 0), "last": usage.get(k, {}).get("last")}
                               for k, (t, d, _, _) in CATEGORIES.items()],
                "vault": list(self.vault)}

    def describe(self):
        lines = ["{} — {}".format(t, LEVEL_RU[self.level(k)]) for k, (t, _, _, _) in CATEGORIES.items()]
        lines.append("Private Vault: " + (", ".join(self.vault) if self.vault else "пусто"))
        return "\n".join(lines)


def usage(days=7):
    """Сколько раз за days дней Chloe пользовалась каждой категорией — из журнала (он и есть история доступа)."""
    import time

    from .journal import journal

    since = time.time() - days * 86400
    out = {}
    with journal.lock:
        rows = journal.db.execute("SELECT ts, detail FROM events WHERE kind = 'tool' AND ts > ?", (since,)).fetchall()
    for r in rows:
        try:
            tool = json.loads(r["detail"] or "{}").get("tool")
        except ValueError:
            continue
        key = TOOL_CATEGORY.get(tool)
        if key:
            u = out.setdefault(key, {"uses": 0, "last": 0})
            u["uses"] += 1
            u["last"] = max(u["last"], r["ts"])
    return out


permissions = Permissions()
