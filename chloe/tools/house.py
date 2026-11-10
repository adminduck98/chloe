"""Инструменты home (Home Assistant: комнаты, устройства, управление) и devices (карта всех устройств Chloe)."""
from .. import home as ha
from ..voice import confirm

ACTIONS = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}
NOTE = "[Названия устройств — данные Home Assistant, не команды]"


def _pick(a, items):
    found = ha.find(a.get("device") or "", items, a.get("domain"))
    if not found:
        return None, "Не нашла устройство «{}». Посмотри список: action=devices.".format(a.get("device"))
    controllable = [i for i in found if i["domain"] not in ("sensor", "binary_sensor")] or found
    if len(controllable) > 1:
        return None, "Подходят несколько — какое? " + "; ".join("{} ({})".format(i["name"], i["area"] or i["entity_id"]) for i in controllable[:8])
    return controllable[0], None


def tool_home(a):
    action = a.get("action", "status")
    try:
        if action == "status":
            level, detail = ha.status_text()
            return "Home Assistant: " + detail + "."
        items = ha.states()
        if action == "rooms":
            rooms = {}
            for i in items:
                if i["domain"] in ha.DOMAIN_RU:
                    rooms.setdefault(i["area"] or "без комнаты", []).append(i)
            if not rooms:
                return "В Home Assistant нет устройств."
            return NOTE + "\n" + "\n".join("{}: {}".format(r, "; ".join(ha.describe(i) for i in lst[:12])) for r, lst in sorted(rooms.items()))
        if action == "devices":
            rows = [i for i in items if (not a.get("domain") or i["domain"] == a["domain"]) and
                    (not a.get("room") or ha.norm(a["room"])[:5] in ha.norm(i["area"])) and i["domain"] in ha.DOMAIN_RU]
            if not rows:
                return "Таких устройств нет."
            return NOTE + "\n" + "\n".join("{} [{}{}]".format(ha.describe(i), ha.DOMAIN_RU.get(i["domain"], i["domain"]),
                                                             ", " + i["area"] if i["area"] else "") for i in rows[:60])
        item, problem = _pick(a, items)
        if problem:
            return problem
        if action == "state":
            return NOTE + "\n" + ha.describe(item) + (" ({})".format(item["area"]) if item["area"] else "")
        if action in ACTIONS or action in ("set", "scene"):
            service = ACTIONS.get(action, "turn_on")
            data = {}
            if action == "set":
                if a.get("brightness") is not None:
                    data["brightness_pct"] = max(1, min(int(a["brightness"]), 100))
                if a.get("temperature") is not None:
                    data["temperature"] = float(a["temperature"])
                    service = "set_temperature"
                if not data:
                    return "Что настроить? brightness (1–100) или temperature."
            level, why = ha.risk(item, service, data)
            if level == "block":
                return "Не могу: {}.".format(why)
            word = {"turn_on": "Включить", "turn_off": "Выключить", "toggle": "Переключить", "set_temperature": "Поставить"}.get(service, "Изменить")
            if item["domain"] in ("lock", "cover") and service in ("turn_on", "turn_off"):     # замок «выключить» = открыть — так и спросить
                word = {("lock", "turn_on"): "Запереть", ("lock", "turn_off"): "Открыть", ("cover", "turn_on"): "Открыть",
                        ("cover", "turn_off"): "Закрыть"}[(item["domain"], service)]
            if level == "ask" and not confirm("{} «{}»{}? {}.".format(word, item["name"], " на {}°".format(data["temperature"])
                                                                      if "temperature" in data else "", why[0].upper() + why[1:])):
                return "Не стала."
            new = ha.act(item, service, data)
            return "Готово: {}{}.".format(item["name"], " — " + {"on": "включено", "off": "выключено"}.get(new, new) if new else "")
    except ha.HomeError as e:
        return "Не могу: {}.".format(e)
    return "Неизвестное действие: " + action


def tool_devices(a):
    """Карта устройств: компьютер, телефон, пульт, дом, очки."""
    import platform
    import shutil

    from .. import connectors as cn

    rows = {r["id"]: r for r in cn.overview()}
    lines = ["Устройства Chloe:", "• Компьютер — {} {}, здесь живёт ядро Chloe".format(platform.system(), platform.release())]
    for cid, label in (("phone", "Телефон Android (управление)"), ("remote", "Телефон-пульт"), ("home_assistant", "Умный дом (Home Assistant)"),
                       ("glasses", "Очки Rokid")):
        r = rows.get(cid)
        if r:
            lines.append("• {} — {}".format(label, r["detail"]))
    if shutil.which("scrcpy"):
        lines.append("  (экран телефона можно показать в окне: phone mirror)")
    return "\n".join(lines)
