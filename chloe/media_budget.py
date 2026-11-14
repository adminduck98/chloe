"""Бюджет пакета Qwen на картинки и видео: сколько процентов месячного пакета ушло и сколько видео на этой неделе.

Правила пользователя (14.11.2026): видео — дорогое (12 с мультика ≈ 5–11 % месячного пакета), поэтому
- одно видео в неделю (CHLOE_VIDEOS_PER_WEEK, неделя — с понедельника); больше — только если пользователь прямо
  сказал «сверх лимита»;
- перед каждым видео Chloe говорит, сколько пакета уже ушло за месяц и сколько будет после;
- черновик мультика делается без Qwen и в лимит не входит.
Проценты — оценка Chloe по замерам (точный остаток Alibaba показывает только в консоли). Хранится в настройках.
"""
import os
import time

from .settings import settings

WEEKLY_VIDEOS = int(os.environ.get("CHLOE_VIDEOS_PER_WEEK", "1"))
KEY = "media_budget"


def entries():
    return list(settings.get(KEY) or [])


def week_start(now=None):
    t = time.localtime(now or time.time())
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    return midnight - t.tm_wday * 86400


def month_percent(now=None):
    month = time.strftime("%Y-%m", time.localtime(now or time.time()))
    return sum(e.get("percent", 0) for e in entries() if time.strftime("%Y-%m", time.localtime(e["at"])) == month)


def week_videos(now=None):
    since = week_start(now)
    return len({e.get("key") or e["at"] for e in entries() if e.get("kind") == "video" and e["at"] >= since})


def counted(key):
    """Этот проект (ролик, доделываемый после пробы) уже посчитан как видео этой недели."""
    since = week_start()
    return bool(key) and any(e.get("key") == key and e.get("kind") == "video" and e["at"] >= since for e in entries())


def video_block(over_limit=False, key=None, now=None):
    """Причина не делать видео (недельный лимит) или None. over_limit — пользователь прямо попросил сверх лимита."""
    if over_limit or counted(key) or week_videos(now) < WEEKLY_VIDEOS:
        return None
    return ("Лимит — {} видео в неделю, на этой неделе уже {}. Следующее — с понедельника. Бесплатно могу сделать "
            "черновик мультика без Qwen. Сверх лимита — только если пользователь прямо скажет «сделай сверх лимита»."
            .format(WEEKLY_VIDEOS, week_videos(now)))


def spend(kind, percent, title="", key=None, now=None):
    """Записать трату: kind — video или image, percent — оценка доли месячного пакета. Возвращает её отметку (для refund)."""
    at = now or time.time()
    log = entries()
    log.append({"at": at, "kind": kind, "percent": round(float(percent), 2), "title": str(title)[:60],
                **({"key": str(key)} if key else {})})
    settings.set(KEY, log[-300:])
    return at


def refund(at):
    """Попытка не удалась, ничего не сделав (Alibaba за неё не берёт) — убрать трату: в лимит и в месяц не считается."""
    log = entries()
    left = [e for e in log if e.get("at") != at]
    if len(left) != len(log):
        settings.set(KEY, left)
        return True
    return False


def note(percent, now=None):
    """Строка для вопроса «Делать?»: сколько ушло за месяц и сколько будет после."""
    was = month_percent(now)
    return "С начала месяца на картинки и видео ушло около {:.0f} % пакета, после этого будет около {:.0f} %.".format(
        was, was + percent)


def status_text(now=None):
    return "Картинки и видео Qwen: за месяц около {:.0f} % пакета, видео на этой неделе: {} из {}.".format(
        month_percent(now), week_videos(now), WEEKLY_VIDEOS)
