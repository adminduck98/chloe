"""YouTube-канал пользователя: статистика и ролики — только чтение.

Вход — тот же OAuth-клиент Google, что у календаря (~/.config/chloe/google_client.json): пользователь сам входит
в браузере и разрешает. В Google Cloud Console у этого проекта должны быть включены «YouTube Data API v3» и
«YouTube Analytics API». Токен — ~/.config/chloe/youtube_token.json (права 600), отдельно от календаря.
Права — только чтение (youtube.readonly, yt-analytics.readonly): Chloe ничего не меняет на канале.

Загрузку роликов Chloe не делает: YouTube оставляет навсегда закрытыми («Доступ ограничен») все ролики,
загруженные через непроверенное API-приложение (проект создан после 28.07.2020 и не прошёл аудит Google).
Публикует пользователь сам в YouTube Studio по готовому пакету (chloe/publish.py).
"""
import datetime

import requests

from . import google_calendar as gc
from .config import KEYS_DIR

TOKEN_FILE = KEYS_DIR / "youtube_token.json"
SCOPE = "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly"
DATA_API = "https://www.googleapis.com/youtube/v3/"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
STUDIO_UPLOAD = "https://www.youtube.com/upload"          # YouTube сам переводит в окно загрузки Studio
WHAT = "YouTube"
TRAFFIC = {"YT_SEARCH": "поиск YouTube", "SUGGESTED": "похожие ролики", "BROWSE": "главная и подписки",
           "SHORTS": "лента Shorts", "EXT_URL": "внешние сайты", "PLAYLIST": "плейлисты", "CHANNEL": "страница канала",
           "NOTIFICATION": "уведомления", "END_SCREEN": "конечные заставки", "NO_LINK_OTHER": "прямые и прочие",
           "SUBSCRIBER": "подписчики", "YT_OTHER_PAGE": "другие страницы YouTube", "HASHTAGS": "хэштеги",
           "RELATED_VIDEO": "связанные ролики", "ANNOTATION": "подсказки", "CAMPAIGN_CARD": "кампании"}

NotConnected = gc.NotConnected


class YouTubeError(Exception):
    pass


def client():
    return gc.client()


def connected():
    return gc.connected(TOKEN_FILE)


def sign_in(**kw):
    return gc.sign_in(scope=SCOPE, token_file=TOKEN_FILE, **kw)


def sign_out():
    return gc.sign_out(TOKEN_FILE)


def _get(url, params):
    resp = requests.get(url, params=params, timeout=20,
                        headers={"Authorization": "Bearer " + gc.access_token(TOKEN_FILE, WHAT)})
    if resp.status_code == 401:
        raise NotConnected("Google не принял доступ — подключите YouTube заново")
    if resp.status_code >= 400:
        try:
            err = resp.json()["error"]
            reason = ((err.get("errors") or [{}])[0].get("reason") or err.get("status") or "")
            msg = err.get("message") or str(resp.status_code)
        except (ValueError, KeyError, TypeError):
            reason, msg = "", str(resp.status_code)
        if reason in ("accessNotConfigured", "SERVICE_DISABLED") or "has not been used" in msg or "is disabled" in msg:
            api = "YouTube Analytics API" if "youtubeanalytics" in url else "YouTube Data API v3"
            raise YouTubeError("в Google Cloud Console у проекта не включён «{}» — включите его (APIs & Services → "
                               "Library) и повторите".format(api))
        if reason == "quotaExceeded":
            raise YouTubeError("исчерпана дневная квота YouTube API — завтра снова будет")
        raise YouTubeError("YouTube: " + msg[:200])
    return resp.json()


def _iso_secs(d):
    """PT1H2M3S → секунды."""
    import re

    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return ((dd * 24 + h) * 60 + mi) * 60 + s


def channel():
    """Канал вошедшего: название, подписчики, просмотры, роликов, плейлист загрузок."""
    items = _get(DATA_API + "channels", {"part": "snippet,statistics,contentDetails", "mine": "true"}).get("items") or []
    if not items:
        raise YouTubeError("у этого аккаунта Google нет YouTube-канала")
    c = items[0]
    st = c.get("statistics", {})
    return {"id": c["id"], "title": c["snippet"]["title"],
            "subscribers": None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0)),
            "views": int(st.get("viewCount", 0)), "videos": int(st.get("videoCount", 0)),
            "uploads": c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")}


def videos_info(ids):
    """Ролики по id: название, дата, длительность, просмотры, лайки, комментарии (порядок — как ids)."""
    if not ids:
        return []
    items = _get(DATA_API + "videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[:50])}).get("items") or []
    by = {}
    for v in items:
        st = v.get("statistics", {})
        secs = _iso_secs(v.get("contentDetails", {}).get("duration"))
        by[v["id"]] = {"id": v["id"], "title": v["snippet"]["title"], "published": v["snippet"].get("publishedAt", "")[:10],
                       "secs": secs, "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                       "comments": int(st.get("commentCount", 0))}
    return [by[i] for i in ids if i in by]


def recent(limit=10, ch=None):
    """Последние ролики канала."""
    ch = ch or channel()
    if not ch.get("uploads"):
        return []
    items = _get(DATA_API + "playlistItems", {"part": "contentDetails", "playlistId": ch["uploads"],
                                              "maxResults": max(1, min(50, limit))}).get("items") or []
    return videos_info([it["contentDetails"]["videoId"] for it in items])


def _report(start, end, metrics, **extra):
    data = _get(ANALYTICS_API, dict({"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
                                     "metrics": metrics}, **extra))
    names = [h["name"] for h in data.get("columnHeaders", [])]
    return [dict(zip(names, row)) for row in data.get("rows") or []]


SUMMARY = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost"


def stats(days=28, today=None):
    """Канал за days дней и прошлый такой же период; лучшие ролики; откуда приходят зрители."""
    today = today or datetime.date.today()
    end = today - datetime.timedelta(days=1)                      # за сегодня YouTube ещё не досчитал
    start = end - datetime.timedelta(days=days - 1)
    prev_end = start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=days - 1)
    ch = channel()
    now = (_report(start, end, SUMMARY) or [{}])[0]
    before = (_report(prev_start, prev_end, SUMMARY) or [{}])[0]
    top = _report(start, end, "views,averageViewPercentage,subscribersGained", dimensions="video", sort="-views", maxResults=5)
    titles = {v["id"]: v for v in videos_info([r["video"] for r in top])}
    for r in top:
        r["title"] = titles.get(r["video"], {}).get("title", r["video"])
    traffic = _report(start, end, "views", dimensions="insightTrafficSourceType", sort="-views")
    return {"channel": ch, "days": days, "from": start.isoformat(), "to": end.isoformat(), "now": now, "before": before,
            "top": top, "traffic": traffic}


def _n(x):
    x = int(round(x or 0))
    return "{:,}".format(x).replace(",", " ")


def _delta(now, before, days):
    if not before:
        return ""
    ch = (now - before) / before * 100
    return " ({}{:.0f} % к прошлым {} дн.)".format("+" if ch >= 0 else "", ch, days)


def describe_stats(s):
    """Сводка статистики словами (для модели и голоса)."""
    ch, now, before, days = s["channel"], s["now"], s["before"], s["days"]
    lines = ["Канал «{}»: {} подписчиков, {} роликов, {} просмотров всего.".format(
        ch["title"], "скрыто" if ch["subscribers"] is None else _n(ch["subscribers"]), _n(ch["videos"]), _n(ch["views"]))]
    if not now:
        lines.append("За {} дней ({} — {}) данных нет: просмотров не было или YouTube ещё не посчитал.".format(days, s["from"], s["to"]))
        return "\n".join(lines)
    d = lambda k: _delta(now.get(k, 0), before.get(k, 0), days)
    lines.append("За {} дней ({} — {}):".format(days, s["from"], s["to"]))
    lines.append("- просмотры: {}{}".format(_n(now.get("views")), d("views")))
    lines.append("- время просмотра: {} ч{}".format(_n(now.get("estimatedMinutesWatched", 0) / 60), d("estimatedMinutesWatched")))
    lines.append("- средняя длительность просмотра: {} с, средний % просмотра: {:.0f} %".format(
        _n(now.get("averageViewDuration")), now.get("averageViewPercentage") or 0))
    lines.append("- подписчики: +{} / −{}".format(_n(now.get("subscribersGained")), _n(now.get("subscribersLost"))))
    if s["top"]:
        lines.append("Лучшие ролики за период:")
        for r in s["top"]:
            lines.append("- «{}»: {} просмотров, досматривают {:.0f} %, +{} подписчиков".format(
                r["title"], _n(r.get("views")), r.get("averageViewPercentage") or 0, _n(r.get("subscribersGained"))))
    total = sum(r.get("views", 0) for r in s["traffic"]) or 0
    if total:
        parts = ["{} {:.0f} %".format(TRAFFIC.get(r["insightTrafficSourceType"], r["insightTrafficSourceType"].lower()),
                                      r["views"] / total * 100) for r in s["traffic"][:5]]
        lines.append("Откуда зрители: " + ", ".join(parts) + ".")
    lines.append("CTR обложек (показы → клики) API не отдаёт — он в YouTube Studio → Аналитика → Охват.")
    return "\n".join(lines)


def describe_videos(vids):
    if not vids:
        return "На канале пока нет роликов."
    out = []
    for v in vids:
        kind = "{}:{:02d}".format(v["secs"] // 60, v["secs"] % 60)
        out.append("- {} «{}» ({}): {} просмотров, {} лайков, {} комментариев".format(
            v["published"], v["title"], kind, _n(v["views"]), _n(v["likes"]), _n(v["comments"])))
    return "Последние ролики:\n" + "\n".join(out)
