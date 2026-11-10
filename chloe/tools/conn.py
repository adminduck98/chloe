"""Инструмент connectors — реестр подключений: статус, проверка, выключить/включить, забыть."""
import time

from .. import connectors as cn
from ..voice import confirm

ICON = {"ok": "✓", "off": "–", "fail": "✗", "paused": "⏸", "planned": "…"}


def tool_connectors(a):
    action = a.get("action", "list")
    if action in ("list", "check"):
        rows = cn.overview(deep=action == "check")
        lines = []
        for r in rows:
            last = time.strftime("%d.%m %H:%M", time.localtime(r["last"])) if r["last"] else "—"
            lines.append("{} {} — {}{}".format(ICON.get(r["level"], "?"), r["name"], r["detail"],
                                              " (за неделю {} раз, последний {})".format(r["uses"], last) if r["tools"] else ""))
        return "Подключения{}:\n".format(" (проверены вживую)" if action == "check" else "") + "\n".join(lines) + (
            "\nОснову (мозги, голос) выключить нельзя. Остальное — «выключи телеграм», «забудь календарь».")
    c = cn.find(a.get("name") or "")
    if not c:
        return "Нет такого подключения. Есть: " + ", ".join(x.name for x in cn.REGISTRY)
    if action == "show":
        r = next(x for x in cn.overview() if x["id"] == c.id)
        return "{}: {}. Статус: {}. Инструменты: {}. {}{}".format(
            c.name, c.what, r["detail"], ", ".join(r["tools"]) or "—", ("Подключить: " + c.connect_hint + ". ") if c.connect_hint else "",
            ("Где хранится вход: " + c.data + ".") if c.data else "")
    if c.kind == cn.CORE:
        return "«{}» — основа Chloe: её не выключить, только проверить (action=check).".format(c.name)
    if c.kind == "planned":
        return "«{}» ещё не подключено — это в плане проекта.".format(c.name)
    if action == "off":
        cn.set_on(c.id, False)
        return "Выключила «{}»: его инструменты закрыты, вход и данные не тронуты. Включить — «включи {}».".format(c.name, c.name.lower())
    if action == "on":
        if cn.is_on(c.id):
            return "«{}» и так включено.".format(c.name)
        if not confirm("Включить подключение «{}»?".format(c.name)):
            return "Оставила выключенным."
        cn.set_on(c.id, True)
        return "Включила «{}».".format(c.name)
    if action == "forget":
        if not c.can_forget:
            return "У «{}» нечего забывать — его можно только выключить.".format(c.name)
        if not confirm("Забыть «{}»: выйти из аккаунта и стереть вход? Подключать придётся заново.".format(c.name)):
            return "Не стала."
        return "{}: {}.".format(c.name, c.forget())
    return "Неизвестное действие: " + action
