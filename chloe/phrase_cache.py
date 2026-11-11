"""Готовые короткие фразы: «Да?», «Остановилась.», «Хорошо.» звучат сразу, без похода на сервер голоса.

Короткая фраза (до MAX_CHARS знаков) один раз озвучивается и сохраняется mp3 в ~/.chloe/voices/phrases;
дальше играет из файла (замер 11.11.2026: «Да?» с сервера — 1–1,8 с до первого звука). Файл привязан к голосу
и тексту: сменили голос — фразы запишутся заново. Хранится не больше MAX_FILES фраз: старые удаляются.
При запуске частые фразы озвучиваются заранее, в фоне.
"""
import hashlib
import os
import threading

from .config import DATA

DIR = DATA / "voices" / "phrases"
MAX_CHARS = 60
MAX_FILES = 200
COMMON = ("Да?", "Остановилась.", "Хорошо.", "До встречи!", "Секунду.", "Готово.")
_lock = threading.Lock()
_heard = {}              # сколько раз фраза звучала с запуска: в запас — только частые и повторившиеся


def worth(text):
    """Стоит ли записать фразу в запас: из частых или уже звучала. Новая короткая фраза идёт потоком
    (первый звук ~1 с), а не целым файлом (~2,3 с) — разовые ответы в запас не нужны."""
    if not fits(text):
        return False
    t = text.strip()
    _heard[t] = _heard.get(t, 0) + 1
    return t in COMMON or _heard[t] >= 2


def key(text, voice):
    return hashlib.sha1("{}|{}".format(voice, text.strip()).encode()).hexdigest()[:20]


def fits(text):
    t = (text or "").strip()
    return 0 < len(t) <= MAX_CHARS and "\n" not in t


def path(text, voice):
    return DIR / (key(text, voice) + ".mp3")


def get(text, voice):
    """Путь к готовому mp3 или None."""
    if not fits(text):
        return None
    p = path(text, voice)
    if p.exists() and p.stat().st_size > 0:
        try:
            os.utime(p)                      # недавно звучавшие — последними под удаление
        except OSError:
            pass
        return p
    return None


def put(text, voice, data):
    if not (fits(text) and data):
        return None
    with _lock:
        DIR.mkdir(parents=True, exist_ok=True)
        p = path(text, voice)
        tmp = p.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        files = sorted(DIR.glob("*.mp3"), key=lambda f: f.stat().st_mtime)
        for old in files[:-MAX_FILES]:
            try:
                old.unlink()
            except OSError:
                pass
    return p


def warm(voice, make, phrases=COMMON):
    """Озвучить частые фразы заранее (в фоне при запуске). make(text) → mp3 или None."""
    done = 0
    for t in phrases:
        if get(t, voice) is None:
            data = make(t)
            if data:
                put(t, voice, data)
                done += 1
    return done
