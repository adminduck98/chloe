"""Окно Chloe голосом: открыть терминал, файлы, проекты, входящие; раскладки экрана; быстрые кнопки.

«Хлоя, открой терминал», «покажи Загрузки», «закрой всё лишнее», «включи раскладку Работа»,
«сделай кнопку „Отчёт“: отчёт за неделю — расходы, доходы, что сделано», «убери кнопку Отчёт».
Быстрая кнопка — это сохранённая просьба: нажатие передаёт её Chloe, как будто сказали голосом.
Хранится в ~/.chloe/settings.json (quick_buttons).
"""
from ..brain import brain
from ..settings import settings

WINDOWS = {"terminal": "терминал", "files": "файлы", "projects": "проекты", "inbox": "входящие", "palette": "поиск по функциям"}
LAYOUTS = ("Работа", "Студия", "Тишина")
MAX_BUTTONS = 12
DEFAULT_BUTTONS = [
    {"label": "Утренний план", "request": "утренний план: что сегодня, сроки, задачи"},
    {"label": "Что в Telegram", "request": "что нового в телеграме"},
    {"label": "Отчёт за неделю", "request": "отчёт за неделю: расходы, доходы, что сделано"},
    {"label": "Загрузки", "request": "посмотри, что лежит в Загрузках, и предложи, как разложить"},
]


def buttons():
    saved = settings.get("quick_buttons")
    return list(saved) if isinstance(saved, list) else [dict(b) for b in DEFAULT_BUTTONS]


def save_buttons(items):
    clean = []
    for b in items or []:
        if not isinstance(b, dict):
            continue
        label, request = str(b.get("label", "")).strip()[:40], str(b.get("request", "")).strip()[:500]
        if label and request and not any(x["label"].lower() == label.lower() for x in clean):
            clean.append({"label": label, "request": request})
    clean = clean[:MAX_BUTTONS]
    settings.set("quick_buttons", clean)
    brain.js("chloeUI", {"action": "buttons", "items": clean})
    return clean


def tool_ui(a):
    action = a.get("action", "")
    if action in ("open", "close", "toggle"):
        win = a.get("window", "")
        if win not in WINDOWS:
            return "Не знаю такого окна. Есть: " + ", ".join(WINDOWS.values()) + "."
        brain.js("chloeUI", {"action": action, "window": win, "path": a.get("path") or ""})
        return "{}: {}.".format({"open": "Открыла", "close": "Закрыла", "toggle": "Переключила"}[action], WINDOWS[win]) + \
            (" Папка: " + a["path"] + "." if a.get("path") and win == "files" else "")
    if action == "close_all":
        brain.js("chloeUI", {"action": "close_all"})
        return "Закрыла мини-окна и панели."
    if action == "layout":
        name = (a.get("name") or "").strip()
        if not name:
            return "Какую раскладку? Есть: " + ", ".join(LAYOUTS) + " и сохранённые в окне."
        brain.js("chloeUI", {"action": "layout", "name": name})
        return "Включаю раскладку «{}».".format(name)
    if action == "save_layout":
        name = (a.get("name") or "").strip()[:30]
        if not name:
            return "Как назвать раскладку?"
        brain.js("chloeUI", {"action": "save_layout", "name": name})
        return "Запомнила, как сейчас стоят окна, — раскладка «{}».".format(name)
    if action == "list_buttons":
        items = buttons()
        return "Быстрые кнопки: " + "; ".join("«{}» — {}".format(b["label"], b["request"]) for b in items) if items else "Быстрых кнопок нет."
    if action == "add_button":
        label, request = (a.get("label") or "").strip(), (a.get("request") or "").strip()
        if not label or not request:
            return "Нужны название кнопки (label) и просьба, которую она передаёт (request)."
        items = [b for b in buttons() if b["label"].lower() != label.lower()] + [{"label": label, "request": request}]
        if len(items) > MAX_BUTTONS:
            return "Кнопок уже {} — уберите какую-нибудь.".format(MAX_BUTTONS)
        save_buttons(items)
        return "Сделала кнопку «{}». Нажатие: «{}».".format(label, request)
    if action == "remove_button":
        label = (a.get("label") or "").strip().lower()
        items = buttons()
        left = [b for b in items if b["label"].lower() != label]
        if len(left) == len(items):
            return "Нет кнопки «{}».".format(a.get("label"))
        save_buttons(left)
        return "Убрала кнопку «{}».".format(a.get("label"))
    return "Не поняла действие: " + str(action)
