"""Над чем пользователь работает сейчас — сводка из истории окон (её ведёт постоянное зрение, chloe/vision.py).

Из заголовков окон за последний час: проект (по названиям проектов из «Проектов» в заголовке: «chloe-main» → chloe),
программа (Visual Studio Code, Brave, Терминал…), файл (app.py), сколько минут. Эта строка уходит мозгу с каждой
просьбой — «исправь ошибку», «продолжим», «что я тут делал?» понятны без объяснений.
Только заголовки окон и время — без снимков; приватные окна не считаются. Всё живёт в памяти, на диск не пишется.
"""
import re

WINDOW = 60 * 60          # смотрим последний час
MIN_SECONDS = 120         # меньше двух минут работы — сводки нет
SELF = re.compile(r"^(chloe|py — chloe)$", re.I)     # окно самой Chloe — не работа
FILE = re.compile(r"[\w.-]+\.(?:py|js|ts|tsx|jsx|html|css|md|txt|json|ya?ml|toml|sh|pdf|docx?|xlsx?|pptx?|csv|epub|fb2)\b", re.I)
TERMINAL = re.compile(r"^[\w.-]+@[\w.-]+:\s*(\S+)")
APPS = (("visual studio code", "VS Code"), ("code - oss", "VS Code"), ("pycharm", "PyCharm"), ("brave", "Brave"),
        ("firefox", "Firefox"), ("chrome", "Chrome"), ("telegram", "Telegram"), ("libreoffice", "LibreOffice"),
        ("nemo", "Файлы"), ("claude", "Claude"), ("obs", "OBS"), ("gimp", "GIMP"), ("blender", "Blender"))


def app_of(title):
    t = title.lower()
    if TERMINAL.match(title):
        return "Терминал"
    for key, name in APPS:
        if key in t:
            return name
    parts = re.split(r"\s+[—–-]\s+", title)
    return parts[-1].strip()[:40] if len(parts) > 1 else title.strip()[:40]


def file_of(title):
    m = FILE.search(title)
    return m.group(0) if m else ""


def project_of(title, projects):
    t = title.lower().replace("ё", "е")
    m = TERMINAL.match(title)
    hay = t + " " + (m.group(1).lower() if m else "")
    for p in sorted(projects, key=len, reverse=True):          # длинное название — точнее
        key = p.lower().replace("ё", "е")
        if len(key) >= 3 and key in hay:
            return p
    return ""


def spans(rows, now, window=WINDOW):
    """[(начало, секунды, заголовок)] за последнее окно времени. rows — (время смены окна, заголовок) по порядку."""
    start = now - window
    out = []
    for i, (t, title) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else now
        a, b = max(t, start), min(end, now)
        if b > a and title and not SELF.match(title.strip()):
            out.append((a, b - a, title))
    return out


def summary(rows, now, projects=(), private=lambda title: False):
    """Сводка для мозга или "" — если работы за час почти не было."""
    items = [(a, s, title) for a, s, title in spans(rows, now) if not private(title)]
    if sum(s for _, s, _ in items) < MIN_SECONDS:
        return ""
    by_project, by_app = {}, {}
    for _, s, title in items:
        p = project_of(title, projects)
        if p:
            by_project[p] = by_project.get(p, 0) + s
        app = app_of(title)
        by_app[app] = by_app.get(app, 0) + s
    last = items[-1][2]
    current = app_of(last)
    streak = 0                                                  # сколько подряд в этой программе
    for _, s, title in reversed(items):
        if app_of(title) != current:
            break
        streak += s
    parts = []
    if by_project:
        main = max(by_project, key=by_project.get)
        parts.append("проект «{}» — {} мин за последний час".format(main, round(by_project[main] / 60)))
    f = file_of(last)
    parts.append("сейчас {}{} ({} мин)".format(current, ", файл " + f if f else "", max(1, round(streak / 60))))
    others = sorted(((a, s) for a, s in by_app.items() if a != current and s >= 60), key=lambda x: -x[1])[:3]
    if others:
        parts.append("ещё было: " + ", ".join("{} {} мин".format(a, round(s / 60)) for a, s in others))
    return "[Работа: {}. «Исправь ошибку», «продолжим», «что тут» — скорее всего про это.]".format("; ".join(parts))
