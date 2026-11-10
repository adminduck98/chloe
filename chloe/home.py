"""Home Assistant — умный дом и офис: комнаты, устройства, состояние, включить / выключить / настроить.

Подключение: адрес Home Assistant и долгосрочный токен (профиль пользователя в HA → «Безопасность» → «Долгосрочные токены
доступа») — в ~/.config/chloe/keys.env строками HA_URL=http://homeassistant.local:8123 и HA_TOKEN=…; токен Chloe не видит
и не показывает. Работает только в домашней сети, через официальный REST API Home Assistant.
Безопасность — по виду устройства:
- сразу: свет, вентиляторы, медиа, сцены, обычные выключатели, температура в разумных пределах (16–28 °C);
- с вопросом «да/нет»: замки, сигнализация, ворота и шторы-двери, сирены, краны, бойлеры, скрипты и автоматизации,
  выключатели с «обогрев», «котёл», «насос», «сервер», «холодильник» в названии;
- «только смотреть» (CHLOE_HOME_READONLY=1 или «Подключения» → выключить) — ничего не меняет.
Безопасный режим и выключенное подключение закрывают всё. Каждое действие — в журнале.
"""
import os
import re

import requests

TIMEOUT = 8
SAFE = {"light", "fan", "media_player", "scene", "input_boolean", "switch", "climate", "humidifier", "remote", "button", "number",
        "select", "input_number", "input_select"}
RISKY = {"lock", "alarm_control_panel", "cover", "siren", "valve", "water_heater", "script", "automation", "vacuum", "camera"}
RISKY_WORDS = re.compile(r"обогрев|котел|котёл|насос|сервер|холодильник|морозил|бойлер|heater|boiler|pump|server|fridge|freezer|gate|ворот|дверь|door",
                         re.I)
TEMP_RANGE = (16, 28)
DOMAIN_RU = {"light": "свет", "switch": "выключатель", "fan": "вентилятор", "climate": "климат", "cover": "шторы/ворота",
             "lock": "замок", "sensor": "датчик", "binary_sensor": "датчик", "media_player": "медиа", "scene": "сцена",
             "script": "скрипт", "automation": "автоматизация", "alarm_control_panel": "сигнализация", "vacuum": "пылесос",
             "camera": "камера", "siren": "сирена", "valve": "кран", "water_heater": "бойлер", "humidifier": "увлажнитель"}


class HomeError(Exception):
    pass


def creds():
    url = (os.environ.get("HA_URL") or "").rstrip("/")
    token = os.environ.get("HA_TOKEN") or ""
    return url, token


def configured():
    url, token = creds()
    return bool(url and token)


def readonly():
    return os.environ.get("CHLOE_HOME_READONLY") == "1"


def _call(method, path, body=None, session=None):
    url, token = creds()
    if not (url and token):
        raise HomeError("Home Assistant не подключён: нужны HA_URL и HA_TOKEN в ~/.config/chloe/keys.env")
    session = session or requests
    try:
        r = session.request(method, url + path, json=body, timeout=TIMEOUT,
                            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise HomeError("Home Assistant не отвечает ({})".format(type(e).__name__)) from None
    if r.status_code == 401:
        raise HomeError("Home Assistant не принял токен — создайте новый долгосрочный токен")
    if r.status_code >= 400:
        raise HomeError("Home Assistant: HTTP {}".format(r.status_code))
    try:
        return r.json()
    except ValueError:
        return r.text


def ping():
    data = _call("GET", "/api/")
    return isinstance(data, dict) and "message" in data


def states():
    """[{entity_id, domain, name, state, attrs, area}] — все устройства."""
    rows = _call("GET", "/api/states") or []
    areas = entity_areas([r["entity_id"] for r in rows])
    out = []
    for r in rows:
        eid = r["entity_id"]
        domain = eid.split(".", 1)[0]
        attrs = r.get("attributes") or {}
        out.append({"entity_id": eid, "domain": domain, "name": attrs.get("friendly_name") or eid, "state": r.get("state"),
                    "attrs": attrs, "area": areas.get(eid) or ""})
    return out


def entity_areas(ids):
    """Комнаты устройств через шаблоны Home Assistant (REST /api/template)."""
    if not ids:
        return {}
    tpl = "{% set ns = namespace(o={}) %}{% for a in areas() %}{% for e in area_entities(a) %}" \
          "{% set ns.o = dict(ns.o, **{e: area_name(a)}) %}{% endfor %}{% endfor %}{{ ns.o | tojson }}"
    try:
        import json

        data = _call("POST", "/api/template", {"template": tpl})
        return json.loads(data) if isinstance(data, str) else (data or {})
    except (HomeError, ValueError):
        return {}


def norm(t):
    return re.sub(r"\s+", " ", str(t).lower().replace("ё", "е")).strip()


def find(name, items=None, domain=None):
    """Устройство по названию (как в HA), entity_id или «свет в гостиной». Возвращает список подходящих."""
    items = items if items is not None else states()
    if domain:
        items = [i for i in items if i["domain"] == domain]
    n = norm(name)
    exact = [i for i in items if norm(i["name"]) == n or i["entity_id"] == name]
    if exact:
        return exact
    words = [w for w in n.split() if len(w) > 2]
    stems = [w[:max(3, len(w) - 2)] for w in words]
    hits = [i for i in items if all(s in norm(i["name"] + " " + i["area"] + " " + DOMAIN_RU.get(i["domain"], "")) for s in stems)]
    return hits


def risk(item, service, data=None):
    """("low"|"ask"|"block", почему)."""
    if readonly():
        return "block", "Home Assistant в режиме «только смотреть»"
    d = item["domain"]
    if d in ("sensor", "binary_sensor", "sun", "weather", "zone", "person", "device_tracker"):
        return "block", "это датчик — им нельзя управлять"
    if d in RISKY:
        return "ask", "{} — важное устройство".format(DOMAIN_RU.get(d, d))
    if RISKY_WORDS.search(item["name"]) and service in ("turn_off", "toggle", "turn_on"):
        return "ask", "«{}» — выключение или включение может навредить".format(item["name"])
    if d == "climate" and data and data.get("temperature") is not None:
        t = float(data["temperature"])
        if not TEMP_RANGE[0] <= t <= TEMP_RANGE[1]:
            return "ask", "температура {}° — вне обычных {}–{}°".format(t, *TEMP_RANGE)
    if d not in SAFE:
        return "ask", "устройство вида «{}»".format(d)
    return "low", ""


def act(item, service, data=None):
    """Вызов службы Home Assistant для устройства. Возвращает новое состояние (если HA его вернул)."""
    body = dict(data or {}, entity_id=item["entity_id"])
    domain = "homeassistant" if service in ("turn_on", "turn_off", "toggle") and item["domain"] not in ("light", "climate", "cover", "lock") \
        else item["domain"]
    if item["domain"] == "scene":
        domain, service = "scene", "turn_on"
    if item["domain"] == "lock" and service in ("turn_on", "turn_off"):
        service = "lock" if service == "turn_on" else "unlock"
    if item["domain"] == "cover" and service in ("turn_on", "turn_off"):
        service = "open_cover" if service == "turn_on" else "close_cover"
    changed = _call("POST", "/api/services/{}/{}".format(domain, service), body) or []
    mine = [c for c in changed if isinstance(c, dict) and c.get("entity_id") == item["entity_id"]]
    return mine[0].get("state") if mine else None


def describe(i):
    a = i["attrs"]
    extra = []
    if i["domain"] == "light" and a.get("brightness") is not None and i["state"] == "on":
        extra.append("яркость {}%".format(round(a["brightness"] / 2.55)))
    if i["domain"] == "climate":
        if a.get("current_temperature") is not None:
            extra.append("сейчас {}°".format(a["current_temperature"]))
        if a.get("temperature") is not None:
            extra.append("цель {}°".format(a["temperature"]))
    if i["domain"] in ("sensor",) and a.get("unit_of_measurement"):
        return "{}: {} {}".format(i["name"], i["state"], a["unit_of_measurement"])
    state = {"on": "включено", "off": "выключено", "locked": "заперто", "unlocked": "открыто", "open": "открыто", "closed": "закрыто",
             "unavailable": "недоступно", "home": "дома", "not_home": "не дома"}.get(i["state"], i["state"])
    return "{} — {}{}".format(i["name"], state, " ({})".format(", ".join(extra)) if extra else "")


def status_text():
    if not configured():
        return "off", "не подключён: HA_URL и HA_TOKEN в keys.env"
    try:
        ping()
        return "ok", "{} отвечает{}".format(creds()[0], ", только смотреть" if readonly() else "")
    except HomeError as e:
        return "fail", str(e)

