"""Отчёт владельцу за неделю (или месяц): деньги и работа (опрос владельца, 16.11.2026: «отчёт нужен полностью»).

Деньги — из учёта Chloe: мышление (DeepSeek, Claude) в долларах по прайсу, картинки и видео Qwen — сколько сделано
и примерная цена по прайсу Сингапура (оплата по факту). Работа — из журнала: сколько просьб, что делала чаще всего,
что не вышло. Точные суммы — в кабинетах DeepSeek, Anthropic и Alibaba Cloud.
"""
import collections
import time

from . import media_budget, usage

# оплата по факту, Сингапур (прайс 15.11.2026, юани → доллары по 7.1): видео happyhorse 480P ≈ $0.074 за секунду,
# картинка qwen-image ≈ $0.042; секунды видео в учёте не хранятся — берём типичный мультик 20 с
USD_PER_VIDEO = 0.074 * 20
USD_PER_IMAGE = 0.042


def money(days=7, now=None):
    now = now or time.time()
    first = time.strftime("%Y-%m-%d", time.localtime(now - days * 86400))
    brain = collections.Counter()
    for day, models in usage.load().items():
        if day > first:
            for model, m in models.items():
                brain[model] += m.get("usd", 0.0)
    since = now - days * 86400
    media = [e for e in media_budget.entries() if e["at"] >= since]
    videos = [e for e in media if e.get("kind") == "video"]
    images = [e for e in media if e.get("kind") == "image"]
    media_usd = len(videos) * USD_PER_VIDEO + len(images) * USD_PER_IMAGE
    return {"brain": dict(brain), "brain_usd": sum(brain.values()), "videos": videos, "images": len(images),
            "media_usd": media_usd, "total": sum(brain.values()) + media_usd}


def work(days=7, now=None):
    from .journal import journal

    now = now or time.time()
    rows = journal.db.execute("SELECT kind, skill, title, ok FROM events WHERE ts > ?", (now - days * 86400,)).fetchall()
    heard = sum(1 for k, *_ in rows if k == "heard")
    tools = collections.Counter(s for k, s, _, _ in rows if k == "tool")
    failed = collections.Counter(s for k, s, _, ok in rows if k == "tool" and not ok)
    return {"requests": heard, "top": tools.most_common(5), "failed": failed.most_common(3)}


def text(days=7, now=None):
    m, w = money(days, now), work(days, now)
    period = "неделю" if days == 7 else "{} дн.".format(days)
    brain = ", ".join("{} ${:.2f}".format(k.split("+")[0], v) for k, v in sorted(m["brain"].items(), key=lambda kv: -kv[1])
                      if v >= 0.005) or "почти ничего"
    lines = ["Отчёт за {}.".format(period),
             "Деньги: всего около ${:.2f}. Мышление ${:.2f} ({}). Картинки и видео Qwen около ${:.2f}: видео {}{}, "
             "картинок {}.".format(m["total"], m["brain_usd"], brain, m["media_usd"], len(m["videos"]),
                                   " (" + ", ".join("«{}»".format(v.get("title", "")[:30]) for v in m["videos"][:3]) + ")"
                                   if m["videos"] else "", m["images"]),
             "Работа: просьб {}. Чаще всего: {}.".format(
                 w["requests"], ", ".join("{} ({})".format(s, n) for s, n in w["top"]) or "ничего"),
             "Видео на этой неделе: {} из {}.".format(media_budget.week_videos(now), media_budget.WEEKLY_VIDEOS)]
    if w["failed"]:
        lines.append("Не вышло: " + ", ".join("{} ({})".format(s, n) for s, n in w["failed"]) + ".")
    lines.append("Оценка по прайсу; точные суммы — в кабинетах DeepSeek, Anthropic и Alibaba Cloud. Бюджет — $100 в месяц.")
    return "\n".join(lines)


def tool_owner_report(a):
    days = 30 if a.get("period") == "month" else 7
    return text(days)
