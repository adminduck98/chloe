"""Инструмент holyarrs: фильмы, сериалы и музыка на своём сервере HolyArrs — что качается, что выходит, поиск, запросы."""
import webbrowser

from .. import holyarrs as ha


def _intro():
    if ha.configured():
        return ""
    url, _ = ha.creds()
    return ("HolyArrs стоит ({}), но Chloe к нему не подключена: в HolyArrs → Settings → API → API keys сделайте ключ с "
            "правами read и write и добавьте строку HOLYARRS_KEY=… в ~/.config/chloe/keys.env, потом перезапустите "
            "Chloe. Ключ вписывает пользователь сам.".format(url))


def tool_holyarrs(a):
    from ..voice import confirm

    action = a.get("action") or "downloads"
    if action == "open":
        url, _ = ha.creds()
        webbrowser.open(url)
        return "Открыла HolyArrs: {}.".format(url)
    if action == "status" and not ha.configured():
        return _intro()
    if not ha.configured():
        return _intro()
    try:
        if action == "status":
            return "Состояние HolyArrs: " + ha.text(ha.health())
        if action == "downloads":
            return "Загрузки сейчас: " + ha.text(ha.downloads())
        if action == "calendar":
            days = a.get("days") or 14
            return "Выходит в ближайшие {} дн.: ".format(days) + ha.text(ha.calendar(days))
        if action == "search":
            q = str(a.get("query") or "").strip()
            if not q:
                return "Что искать (query): название или описание словами («космический фильм 2014»)."
            return "Найдено (tmdb id — для request): " + ha.text(ha.search(q))
        if action == "library":
            q = str(a.get("query") or "").strip()
            if not q:
                return "Что искать в медиатеке (query)."
            return "В медиатеке: " + ha.text(ha.library(q, a.get("kind") or "all"))
        if action == "asks":
            return "Мои запросы: " + ha.text(ha.my_asks())
        if action == "request":
            tmdb = ha.tmdb_id(a.get("tmdb_id"))
            kind = a.get("kind") if a.get("kind") in ("movie", "show") else "movie"
            title = str(a.get("title") or "").strip() or "TMDB {}".format(tmdb)
            what = "фильм" if kind == "movie" else "сериал"
            if not confirm("Запросить в HolyArrs {} «{}»? Он сам найдёт и скачает его по вашим правилам.".format(what, title)):
                return "Не запрашиваю: пользователь отказался."
            return "Запрос отправлен в HolyArrs: {} «{}». Ответ: {}".format(what, title, ha.text(ha.ask(tmdb, kind)))
    except ha.HolyArrsError as e:
        return "Не получилось: {}.".format(str(e).rstrip("."))
    return "Действия: downloads, calendar, search, library, asks, request, status, open."
