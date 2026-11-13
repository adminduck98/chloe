"""HolyArrs — фильмы, сериалы и музыка на своём сервере (https://github.com/HolyArrs/HolyArrs), в Docker на этом компьютере.

Chloe говорит с его JSON API (/api/v1) ключом из ~/.config/chloe/keys.env: HOLYARRS_KEY=… (HolyArrs → Settings → API →
API keys, права read и write), HOLYARRS_URL — адрес (по умолчанию http://localhost:6262). Ключ Chloe не видит:
файл ключей закрыт для её инструментов.

Маршруты — те же, что у встроенных ИИ-инструментов HolyArrs (app/backend/internal/ai/tools.go): поиск, медиатека,
календарь, загрузки, мои запросы, здоровье; запрос фильма или сериала — POST /api/v1/asks {"id": "tmdb:<id>", "kind"}.
"""
import datetime
import json
import os
import urllib.parse

import requests

DEFAULT_URL = "http://localhost:6262"
TIMEOUT = 15
SKIP = ("poster", "backdrop", "fanart", "banner", "logo", "image", "artwork", "thumb", "trailer", "url", "path", "hash")
MAX_TEXT = 5000


class HolyArrsError(Exception):
    pass


def creds():
    return (os.environ.get("HOLYARRS_URL") or DEFAULT_URL).rstrip("/"), os.environ.get("HOLYARRS_KEY") or ""


def configured():
    return bool(creds()[1])


def _call(method, path, body=None):
    url, key = creds()
    if not key:
        raise HolyArrsError("нет ключа HolyArrs: HolyArrs → Settings → API → API keys (права read и write), строкой "
                            "HOLYARRS_KEY=… в ~/.config/chloe/keys.env, потом перезапустить Chloe")
    try:
        r = requests.request(method, url + "/api/v1" + path, json=body, timeout=TIMEOUT,
                             headers={"X-Api-Key": key, "Accept": "application/json"})
    except requests.RequestException as e:
        raise HolyArrsError("HolyArrs не отвечает на {} ({}) — запущен ли контейнер? «docker compose up -d» в ~/holyarrs"
                            .format(url, type(e).__name__)) from None
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {}
    if r.status_code == 401:
        raise HolyArrsError("HolyArrs не принял ключ — сделайте новый (Settings → API) и замените HOLYARRS_KEY")
    if r.status_code == 403:
        raise HolyArrsError("у ключа нет прав на это ({}) — нужен ключ с правами read и write".format(
            data.get("error", "403") if isinstance(data, dict) else "403"))
    if r.status_code >= 400:
        msg = data.get("error") if isinstance(data, dict) else None
        raise HolyArrsError("HolyArrs: {}".format(msg or r.status_code))
    return data


def slim(v, depth=0):
    """Ответ без картинок, ссылок и путей — модели хватает названий, годов, состояний и id."""
    if depth > 6:
        return None
    if isinstance(v, dict):
        return {k: slim(x, depth + 1) for k, x in v.items()
                if x not in (None, "", [], {}) and not any(s in k.lower() for s in SKIP)}
    if isinstance(v, list):
        return [slim(x, depth + 1) for x in v[:25]]
    if isinstance(v, str) and len(v) > 300:
        return v[:300] + "…"
    return v


def text(v):
    out = json.dumps(slim(v), ensure_ascii=False, separators=(",", ":"))
    return out if len(out) <= MAX_TEXT else out[:MAX_TEXT] + "…(обрезано)"


def health():
    return _call("GET", "/health/states")


def downloads():
    return _call("GET", "/downloads/view")


def calendar(days=14, today=None):
    today = today or datetime.date.today()
    days = max(1, min(60, int(days or 14)))
    return _call("GET", "/calendar?from={}&to={}".format(today.isoformat(), (today + datetime.timedelta(days=days)).isoformat()))


def search(query):
    return _call("GET", "/search?q=" + urllib.parse.quote(str(query)[:200]))


def library(name, kind="all"):
    kind = kind if kind in ("all", "movie", "show", "music") else "all"
    return _call("GET", "/library/search?q={}&kind={}".format(urllib.parse.quote(str(name)[:200]), kind))


def my_asks():
    return _call("GET", "/asks?mine=1")


def tmdb_id(value):
    v = str(value or "").strip().lower().removeprefix("tmdb:")
    if not v.isdigit() or len(v) > 12:
        raise HolyArrsError("нужен TMDB id цифрами (например 693134) — возьми его из результата search")
    return v


def ask(tmdb, kind="movie"):
    """Запросить фильм или сериал: HolyArrs найдёт, скачает и положит в медиатеку по правилам владельца."""
    if kind not in ("movie", "show"):
        raise HolyArrsError("kind — movie или show")
    return _call("POST", "/asks", {"id": "tmdb:" + tmdb_id(tmdb), "kind": kind})
