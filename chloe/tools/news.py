"""Инструменты news (что происходит в мире) и morning_brief (утренняя сводка: погода, дела, новости)."""
import datetime
import time

from .. import news
from ..settings import settings


def tool_news(a):
    action = a.get("action", "headlines")
    if action == "topics":
        want = [news.topic_key(t) for t in (a.get("topics") or [])]
        if not want or None in want:
            return "Темы: {}. Сейчас слежу за: {}.".format(", ".join(news.FEEDS), ", ".join(news.topics()))
        settings.set("news_topics", list(dict.fromkeys(want)))
        return "Запомнила: в сводке новостей — {}.".format(", ".join(news.topics()))
    if action in ("morning_on", "morning_off"):
        settings.set("morning_brief", action == "morning_on")
        return ("Хорошо: при первом запуске утром (с 5 до 12) расскажу сводку — погода, дела, новости."
                if action == "morning_on" else "Утреннюю сводку больше не рассказываю сама — только по просьбе.")
    if action == "search":
        q = (a.get("query") or "").strip()
        if not q:
            return "Нужен query — о чём искать новости."
        try:
            items = news.search(q, int(a.get("count") or 8))
        except Exception as e:
            return "Поиск новостей не ответил ({}).".format(type(e).__name__)
        if not items:
            return "Свежих новостей про «{}» не нашла.".format(q)
        return news.DATA_NOTE + "\n" + news.format_topic("про " + q, items, [], details=True)
    wanted = a.get("topics") or ([a["topic"]] if a.get("topic") else news.topics())
    keys = [k for k in (news.topic_key(t) for t in wanted) if k]
    if not keys:
        return "Таких тем нет. Есть: {}. Своя тема — action=search с query.".format(", ".join(news.FEEDS))
    limit = max(3, min(int(a.get("count") or (8 if len(keys) == 1 else 5)), 15))
    parts = []
    for k in dict.fromkeys(keys):
        items, failed = news.headlines(k, limit)
        parts.append(news.format_topic(k, items, failed, details=bool(a.get("details"))))
    return news.DATA_NOTE + "\n" + "\n".join(parts) + (
        "\nПерескажи коротко своими словами, самое важное первым; называй источник, если это заявление одной стороны.")


DAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")


def _part(name, fn):
    try:
        return fn()
    except Exception as e:   # одна часть сводки не должна ронять всю
        return "{}: не получилось ({})".format(name, type(e).__name__)


def _today_reminders():
    from ..reminders import reminders, when_text

    end = datetime.datetime.combine(datetime.date.today(), datetime.time.max).timestamp()
    rows = [r for r in reminders.pending() if r["due"] <= end]
    return "Напоминания на сегодня: " + ("; ".join("{} — {}".format(when_text(r["due"]), r["text"]) for r in rows) if rows else "нет")


def _calendar():
    from .. import google_calendar as gc
    from .calendar import tool_calendar

    if not gc.connected():
        return ""
    return "Календарь: " + tool_calendar({"action": "list"})


def _payments():
    from ..finance import finance, upcoming_text

    return upcoming_text(finance.due(1))


def _weather():
    from .weather import tool_weather

    return "Погода: " + tool_weather({"days": 1})


def tool_morning_brief(a):
    now = datetime.datetime.now()
    head = "Сегодня {}, {} {}, {:%H:%M}.".format(DAYS[now.weekday()], now.day, MONTHS[now.month - 1], now)
    parts = [head, _part("Погода", _weather), _part("Календарь", _calendar), _part("Напоминания", _today_reminders),
             _part("Платежи", _payments)]
    topics = news.topics()[:3]
    parts.append(_part("Новости", lambda: tool_news({"topics": topics, "count": 4})))
    return ("\n\n".join(p for p in parts if p) +
            "\n\nЭто утренняя сводка: расскажи её голосом коротко и тепло, за минуту — дата, погода (одной фразой), "
            "дела на сегодня, скорые списания денег, если есть, 3–5 главных новостей по одной фразе. Без списков и ссылок.")


def morning_due(now=None):
    """Пора ли рассказать сводку самой: включено, утро, сегодня ещё не рассказывала."""
    now = now or time.time()
    t = time.localtime(now)
    today = time.strftime("%Y-%m-%d", t)
    if not settings.get("morning_brief") or not 5 <= t.tm_hour < 12 or settings.get("brief_day") == today:
        return False
    settings.set("brief_day", today)
    return True
