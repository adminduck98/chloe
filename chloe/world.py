"""World Intelligence — картина внешнего мира: события с координатами для глобуса, рынки, киберугрозы.

Источники — открытые, без ключей, каждый можно выключить («не показывай киберугрозы»):
- quakes   — землетрясения M4.5+ за сутки (USGS);
- disasters — стихийные бедствия с уровнем тревоги: циклоны, наводнения, вулканы, пожары (GDACS, ООН и Еврокомиссия);
- nature   — открытые природные события со спутников: штормы, пожары, вулканы (NASA EONET);
- news     — заголовки из лент Chloe, привязанные к стране или городу по названию в заголовке;
- markets  — курсы ЦБ Узбекистана (с изменением за день) и биткоин / эфир (CoinGecko);
- cyber    — уязвимости, которые уже используют в атаках, за неделю (каталог CISA KEV).
Chloe ничего не предсказывает сама: «сценарии» — это оценка мозга по этим данным, с источниками и оговорками.
Последний снимок — ~/.chloe/world.json (его можно стереть: «очисти историю мира»).
"""
import concurrent.futures
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

from .config import DATA
from .settings import settings

UA = "Mozilla/5.0 (X11; Linux x86_64) Chloe/1.0"
SOURCES = {"quakes": "Землетрясения (USGS)", "disasters": "Стихийные бедствия (GDACS)", "nature": "Природные события (NASA EONET)",
           "news": "Новости на карте", "markets": "Рынки (ЦБ Узбекистана, CoinGecko)", "cyber": "Киберугрозы (CISA KEV)"}
KINDS = {"quake": "землетрясение", "cyclone": "циклон", "flood": "наводнение", "volcano": "вулкан", "fire": "пожар",
         "drought": "засуха", "storm": "шторм", "news": "новость", "other": "событие"}
TTL = 15 * 60
NEAR_KM = 1500
MAX_FIRES = 20
MAX_AGE = 7 * 86400
SNAPSHOT = DATA / "world.json"
_cache = {"at": 0, "data": None}

# основа названия в заголовке → (широта, долгота, как назвать)
PLACES = {
    "узбекист": (41.3, 64.6, "Узбекистан"), "ташкент": (41.3, 69.2, "Ташкент"), "самарканд": (39.65, 66.96, "Самарканд"),
    "бухар": (39.77, 64.42, "Бухара"), "ферган": (40.38, 71.78, "Фергана"), "андижан": (40.78, 72.34, "Андижан"),
    "наманган": (41.0, 71.67, "Наманган"), "каракалпак": (43.8, 59.0, "Каракалпакстан"), "сурхандар": (37.9, 67.6, "Сурхандарья"),
    "хорезм": (41.5, 60.6, "Хорезм"), "арал": (45.0, 60.0, "Арал"),
    "казахст": (48.0, 67.0, "Казахстан"), "кыргыз": (41.2, 74.8, "Кыргызстан"), "киргиз": (41.2, 74.8, "Кыргызстан"),
    "таджикист": (38.9, 71.3, "Таджикистан"), "туркмен": (39.0, 59.6, "Туркменистан"), "афганист": (33.9, 67.7, "Афганистан"),
    "росси": (58.0, 60.0, "Россия"), "москв": (55.75, 37.6, "Москва"), "петербург": (59.9, 30.3, "Санкт-Петербург"),
    "украин": (49.0, 32.0, "Украина"), "киев": (50.45, 30.5, "Киев"), "белорус": (53.7, 28.0, "Беларусь"),
    "сша": (39.0, -98.0, "США"), "вашингтон": (38.9, -77.0, "Вашингтон"), "америк": (39.0, -98.0, "США"),
    "кита": (35.0, 104.0, "Китай"), "пекин": (39.9, 116.4, "Пекин"), "тайван": (23.7, 121.0, "Тайвань"),
    "япони": (36.2, 138.3, "Япония"), "токио": (35.7, 139.7, "Токио"), "коре": (37.0, 127.8, "Корея"),
    "инди": (21.0, 78.0, "Индия"), "пакистан": (30.4, 69.3, "Пакистан"), "иран": (32.4, 53.7, "Иран"),
    "израил": (31.0, 35.0, "Израиль"), "газа": (31.4, 34.4, "Газа"), "палестин": (31.9, 35.2, "Палестина"),
    "сири": (35.0, 38.5, "Сирия"), "ирак": (33.2, 43.7, "Ирак"), "турци": (39.0, 35.2, "Турция"), "стамбул": (41.0, 29.0, "Стамбул"),
    "оаэ": (24.0, 54.0, "ОАЭ"), "абу-даби": (24.45, 54.4, "Абу-Даби"), "дубай": (25.2, 55.3, "Дубай"),
    "сауд": (24.0, 45.0, "Саудовская Аравия"), "египет": (26.8, 30.8, "Египет"), "египт": (26.8, 30.8, "Египет"),
    "герман": (51.2, 10.4, "Германия"), "берлин": (52.5, 13.4, "Берлин"), "франци": (46.6, 2.2, "Франция"),
    "париж": (48.85, 2.35, "Париж"), "британ": (54.0, -2.0, "Великобритания"), "лондон": (51.5, -0.13, "Лондон"),
    "итали": (42.8, 12.5, "Италия"), "испани": (40.0, -3.7, "Испания"), "польш": (52.0, 19.4, "Польша"),
    "брюссел": (50.85, 4.35, "Брюссель"), "евросоюз": (50.85, 4.35, "Евросоюз"), "нато": (50.88, 4.43, "НАТО"),
    "грузи": (42.3, 43.4, "Грузия"), "армени": (40.1, 45.0, "Армения"), "азербайджан": (40.3, 47.7, "Азербайджан"),
    "венесуэл": (7.0, -66.0, "Венесуэла"), "бразили": (-10.0, -52.0, "Бразилия"), "мексик": (23.6, -102.5, "Мексика"),
    "шри-ланк": (7.9, 80.8, "Шри-Ланка"), "эстони": (58.6, 25.0, "Эстония"), "латви": (56.9, 24.6, "Латвия"), "литв": (55.2, 23.9, "Литва"),
    "канад": (56.0, -106.0, "Канада"), "австрали": (-25.0, 134.0, "Австралия"), "индонези": (-2.5, 118.0, "Индонезия"),
}
UZ = {"узбекист", "ташкент", "самарканд", "бухар", "ферган", "андижан", "наманган", "каракалпак", "сурхандар", "хорезм", "арал"}
GDACS_KIND = {"EQ": "quake", "TC": "cyclone", "FL": "flood", "VO": "volcano", "WF": "fire", "DR": "drought"}
EONET_KIND = {"severeStorms": "storm", "wildfires": "fire", "volcanoes": "volcano", "floods": "flood", "drought": "drought"}


def enabled():
    off = set(settings.get("world_off") or [])
    return [s for s in SOURCES if s not in off]


def set_source(name, on):
    if name not in SOURCES:
        return False
    off = set(settings.get("world_off") or [])
    (off.discard if on else off.add)(name)
    settings.set("world_off", sorted(off))
    _cache.update(at=0, data=None)
    return True


def _get(url, timeout=12):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r


def event(kind, title, lat, lon, ts, level, source, url="", detail=""):
    return {"kind": kind, "title": title, "lat": lat, "lon": lon, "ts": ts, "level": level, "source": source, "url": url,
            "detail": detail}


def quakes():
    data = _get("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson").json()
    out = []
    for f in data.get("features", []):
        p, g = f["properties"], f["geometry"]["coordinates"]
        mag = p.get("mag") or 0
        out.append(event("quake", "M{:.1f} — {}".format(mag, p.get("place") or "?"), g[1], g[0], p["time"] / 1000,
                         3 if mag >= 6.5 else 2 if mag >= 5.5 else 1, "USGS", p.get("url", ""),
                         "глубина {:.0f} км{}".format(g[2], ", угроза цунами" if p.get("tsunami") else "")))
    return out


def disasters():
    root = ET.fromstring(_get("https://www.gdacs.org/xml/rss.xml").content)
    ns = {"gdacs": "http://www.gdacs.org", "georss": "http://www.georss.org/georss"}
    import email.utils

    out = []
    for it in root.iter("item"):
        kind = GDACS_KIND.get(it.findtext("gdacs:eventtype", "", ns), "other")
        level = {"Green": 1, "Orange": 2, "Red": 3}.get(it.findtext("gdacs:alertlevel", "", ns), 1)
        if kind == "quake" and level == 1:
            continue                                 # слабые землетрясения уже есть от USGS
        try:
            lat, lon = map(float, it.findtext("georss:point", "", ns).split())
            ts = email.utils.parsedate_to_datetime(it.findtext("pubDate")).timestamp()
        except (ValueError, TypeError):
            continue
        out.append(event(kind, re.sub(r"\s+", " ", it.findtext("title") or "").strip()[:140], lat, lon, ts, level, "GDACS",
                         it.findtext("link") or "", it.findtext("gdacs:country", "", ns)))
    return out


def nature():
    data = _get("https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=5&limit=60", timeout=15).json()
    import datetime

    out = []
    for e in data.get("events", []):
        geo = (e.get("geometry") or [{}])[-1]
        c = geo.get("coordinates")
        if not c or geo.get("type") != "Point":
            continue
        cat = (e.get("categories") or [{}])[0].get("id", "")
        try:
            ts = datetime.datetime.fromisoformat(geo["date"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            ts = time.time()
        out.append(event(EONET_KIND.get(cat, "other"), e.get("title", "")[:140], c[1], c[0], ts, 1, "NASA EONET",
                         (e.get("sources") or [{}])[0].get("url", "")))
    return out


def locate(title, prefer=None):
    """Место по названию в заголовке: (lat, lon, имя) или None. Берётся первое упомянутое: «В Эстонии возмутились
    ультиматумом Германии» — это про Эстонию."""
    low = " " + title.lower().replace("ё", "е") + " "
    best = home = None
    for stem, place in PLACES.items():
        m = re.search(r"[^a-zа-я]" + re.escape(stem), low)
        if not m:
            continue
        if best is None or m.start() < best[0]:
            best = (m.start(), place)
        if prefer and stem in prefer and (home is None or m.start() < home[0]):
            home = (m.start(), place)
    best = home or best                      # лента Узбекистана: «Из США в Узбекистан вернули…» — это про Узбекистан
    return best[1] if best else None


def news_points():
    from . import news

    out = []
    for topic in ("главное", "узбекистан"):
        items, _ = news.headlines(topic, 12)
        for i in items:
            place = locate(i["title"], UZ if topic == "узбекистан" else None)
            if place:
                out.append(event("news", i["title"], place[0], place[1], i["when"] or time.time(), 1,   # уровень тревоги — не про новости
                                 ", ".join(i["sources"]), i.get("link", ""), place[2]))
    return out


def markets():
    from . import finance

    out = []
    try:
        for row in _get(finance.RATES_URL).json():
            if row["Ccy"] in ("USD", "EUR", "RUB", "CNY", "KZT"):
                out.append({"name": row["Ccy"] + "/UZS", "value": float(row["Rate"]), "change": float(row.get("Diff") or 0),
                            "unit": "сум", "source": "ЦБ Узбекистана", "date": row.get("Date", "")})
    except (requests.RequestException, ValueError, KeyError):
        pass
    try:
        c = _get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true").json()
        for key, name in (("bitcoin", "BTC"), ("ethereum", "ETH")):
            if key in c:
                out.append({"name": name, "value": float(c[key]["usd"]), "change_pct": round(float(c[key].get("usd_24h_change") or 0), 2),
                            "unit": "$", "source": "CoinGecko"})
    except (requests.RequestException, ValueError, KeyError):
        pass
    return out


def cyber(days=7, now=None):
    data = _get("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", timeout=20).json()
    since = time.strftime("%Y-%m-%d", time.gmtime((now or time.time()) - days * 86400))
    rows = [v for v in data.get("vulnerabilities", []) if v.get("dateAdded", "") >= since]
    rows.sort(key=lambda v: v.get("dateAdded", ""), reverse=True)
    return [{"id": v["cveID"], "product": "{} {}".format(v.get("vendorProject", ""), v.get("product", "")).strip(),
             "title": v.get("vulnerabilityName", ""), "added": v.get("dateAdded", ""),
             "ransomware": v.get("knownRansomwareCampaignUse") == "Known", "detail": (v.get("shortDescription") or "")[:240],
             "source": "CISA KEV"} for v in rows[:25]]


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


FETCH = {"quakes": quakes, "disasters": disasters, "nature": nature, "news": news_points}


def picture(fresh=False, now=None):
    """Вся картина: {"at", "events", "markets", "cyber", "failed", "home"}. Кеш — 15 минут."""
    now = now or time.time()
    if not fresh and _cache["data"] and now - _cache["at"] < TTL:
        return _cache["data"]
    on = enabled()
    jobs = {name: fn for name, fn in FETCH.items() if name in on}
    if "markets" in on:
        jobs["markets"] = markets
    if "cyber" in on:
        jobs["cyber"] = cyber
    results, failed = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        futures = {name: pool.submit(fn) for name, fn in jobs.items()}
        for name, f in futures.items():
            try:
                results[name] = f.result(timeout=30)
            except Exception:
                failed.append(SOURCES[name])
                results[name] = []
    events = [e for name in FETCH for e in results.get(name, []) if now - e["ts"] <= MAX_AGE]   # «идёт 129 дней» — не событие дня
    fires = sorted((e for e in events if e["kind"] == "fire"), key=lambda e: (-e["level"], -e["ts"]))[:MAX_FIRES]
    events = [e for e in events if e["kind"] != "fire"] + fires                                  # пожаров в мире — сотни
    home = settings.get("city") or {}
    for e in events:
        if home.get("lat") is not None:
            e["km"] = round(distance_km(home["lat"], home["lon"], e["lat"], e["lon"]))
            e["near"] = e["km"] <= NEAR_KM
    seen, unique = set(), []
    for e in sorted(events, key=lambda e: (-e["level"], -e["ts"])):
        key = (e["kind"], round(e["lat"]), round(e["lon"]))       # одно событие из двух источников — один раз
        if e["kind"] != "news" and key in seen:
            continue
        seen.add(key)
        unique.append(e)
    data = {"at": now, "events": unique, "markets": results.get("markets", []), "cyber": results.get("cyber", []),
            "failed": failed, "home": {"lat": home.get("lat"), "lon": home.get("lon"), "name": home.get("name")},
            "sources": {s: (s in on) for s in SOURCES}}
    _cache.update(at=now, data=data)
    try:
        SNAPSHOT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(SNAPSHOT, 0o600)
    except OSError:
        pass
    return data


def clear():
    _cache.update(at=0, data=None)
    try:
        SNAPSHOT.unlink()
        return True
    except OSError:
        return False


def ago(ts, now=None):
    mins = int(((now or time.time()) - ts) // 60)
    if mins < 60:
        return "{} мин назад".format(max(1, mins))
    if mins < 48 * 60:
        return "{} ч назад".format(mins // 60)
    return "{} дн назад".format(mins // 1440)


def line(e):
    near = ", {} км от вас".format(e["km"]) if e.get("near") else ""
    return "• [{}] {} ({}, {}{}){}".format(KINDS.get(e["kind"], e["kind"]), e["title"], e["source"], ago(e["ts"]), near,
                                           " ‼" if e["level"] >= 3 else " !" if e["level"] == 2 else "")
