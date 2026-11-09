"""Город пользователя и погода. Данные — Open-Meteo: бесплатно, без ключа и регистрации.

Город хранится в ~/.chloe/settings.json; Chloe знает его из системной подсказки и меняет голосом
(«Хлоя, я теперь живу в Самарканде»).
"""
import datetime

from ..settings import settings

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# коды погоды WMO → по-русски
WMO = {
    0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "туман с изморозью",
    51: "слабая морось", 53: "морось", 55: "сильная морось", 56: "ледяная морось", 57: "сильная ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
    80: "небольшой ливень", 81: "ливень", 82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def get_json(url, params):
    import requests

    r = requests.get(url, params=params, timeout=10, headers={"User-Agent": "Chloe-assistant"})
    r.raise_for_status()
    return r.json()


def find_city(query):
    """«Самарканд» или «Ташкент, Узбекистан» → место с координатами, либо None."""
    name, _, country = (s.strip() for s in query.partition(","))
    found = get_json(GEO_URL, {"name": name, "count": 10, "language": "ru", "format": "json"}).get("results") or []
    if country:
        found = [p for p in found if country.lower() in (p.get("country") or "").lower()] or found
    if not found:
        return None
    p = found[0]   # Open-Meteo сам ставит первым самый известный город с этим именем
    return {"name": p["name"], "country": p.get("country", ""), "region": p.get("admin1", ""),
            "lat": p["latitude"], "lon": p["longitude"], "timezone": p.get("timezone", "auto")}


def place_text(p):
    return ", ".join(x for x in (p["name"], p.get("region") if p.get("region") != p["name"] else "", p.get("country")) if x)


def tool_set_city(a):
    place = find_city(a["city"])
    if place is None:
        return "Не найдено место «{}». Уточни у пользователя название.".format(a["city"])
    settings.set("city", place)
    return "Запомнила город: {}.".format(place_text(place))


def deg(t):
    return "{:+d}°".format(round(t)).replace("+0°", "0°")


def tool_weather(a):
    if a.get("city"):
        place = find_city(a["city"])
        if place is None:
            return "Не найдено место «{}».".format(a["city"])
    else:
        place = settings.get("city")
        if not place:
            return ("Не могу: город пользователя не знаю. Спроси, в каком городе он живёт, "
                    "и сохрани ответ инструментом set_city.")
    days = max(1, min(int(a.get("days") or 3), 7))
    f = get_json(FORECAST_URL, {
        "latitude": place["lat"], "longitude": place["lon"], "timezone": place.get("timezone") or "auto",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": days, "wind_speed_unit": "ms"})
    c = f["current"]
    lines = ["{} — сейчас ({} по местному времени): {}, {} (ощущается {}), ветер {} м/с, влажность {}%.".format(
        place_text(place), c["time"][-5:], WMO.get(c["weather_code"], "погода"), deg(c["temperature_2m"]),
        deg(c["apparent_temperature"]), round(c["wind_speed_10m"]), c["relative_humidity_2m"])]
    d = f["daily"]
    for i, day in enumerate(d["time"]):
        date = datetime.date.fromisoformat(day)
        label = ("сегодня", "завтра")[i] if i < 2 else WEEKDAYS[date.weekday()]
        rain = d["precipitation_probability_max"][i]
        lines.append("{} {}: {}, от {} до {}{}.".format(
            label, date.strftime("%d.%m"), WMO.get(d["weather_code"][i], "погода"),
            deg(d["temperature_2m_min"][i]), deg(d["temperature_2m_max"][i]),
            ", осадки {}%".format(rain) if rain is not None else ""))
    return "\n".join(lines)
