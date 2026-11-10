"""Приветствие при запуске — живое: по времени суток, с обращением из памяти («босс»), не повторяет прошлое.

Модель тут не нужна (приветствие должно звучать сразу, без ожидания сети): фразы — набор по времени суток,
обращение — из долгосрочной памяти («Обращаться к нему «босс»»), последняя фраза помнится и не повторяется подряд.
"""
import random
import re
import time

from .settings import settings

PARTS = {
    "morning": ["Доброе утро{a}!", "Утро доброе{a}.", "С добрым утром{a}!", "Доброе утро{a}, я на месте."],
    "day": ["Привет{a}!", "Добрый день{a}.", "Я здесь{a}.", "Привет{a}, я на связи.", "Снова здравствуй{a}!"],
    "evening": ["Добрый вечер{a}!", "Вечер добрый{a}.", "Привет{a}, вечер на дворе.", "Добрый вечер{a}, я с тобой."],
    "night": ["Не спится{a}?", "Доброй ночи{a}, я тут.", "Привет{a}. Поздновато, но я рядом.", "Я здесь{a}, даже ночью."],
}
TAILS = ["Слушаю.", "Чем займёмся?", "Что делаем?", "Я слушаю.", "Говори.", "Чем помочь?", "Готова."]
MORNING_BRIEF = ["Доброе утро{a}! Сейчас расскажу, что сегодня.", "Утро доброе{a}! Вот что на сегодня.",
                 "С добрым утром{a}! Коротко о дне."]


def part_of_day(hour):
    if hour < 5 or hour >= 23:
        return "night"
    return "morning" if hour < 12 else "day" if hour < 18 else "evening"


def address():
    """Как обращаться к пользователю — из памяти («Обращаться к нему «босс»»), или пусто."""
    try:
        from .memory import memory

        for m in reversed(memory.items):
            found = re.search(r"[Оо]бращаться\s+к\s+(?:нему|ней|пользователю)\s+«([^»]{1,30})»", m.get("text", ""))
            if found:
                return found.group(1)
    except Exception:
        pass
    return ""


def pick(options, last, rnd):
    fresh = [o for o in options if o != last] or options
    return rnd.choice(fresh)


def greeting(now=None, brief=False, rnd=random):
    """Новая фраза приветствия; прошлая (из настроек) подряд не повторяется."""
    hour = time.localtime(now or time.time()).tm_hour
    a = address()
    last = settings.get("last_greeting") or ""
    for _ in range(6):
        if brief:
            text = pick(MORNING_BRIEF, last, rnd)
        else:
            head = rnd.choice(PARTS[part_of_day(hour)])
            tails = [t for t in TAILS if not (t.startswith("Я ") and "я " in head.lower() + " ")]   # не «Я здесь. Я слушаю.»
            text = head if head.endswith(("?", "рядом.", "ночью.")) and rnd.random() < 0.5 else head + " " + rnd.choice(tails)
        text = text.format(a=", " + a if a and rnd.random() < 0.6 else "")
        if text != last:
            break
    settings.set("last_greeting", text)
    return text
