"""System State — единая картина «как я сейчас»: что работает, что выключено, что сломалось.

Быстрая проверка (без сети, доли секунды) — для панели «Ядро» и вопроса «как ты?»: ключи и модели, голос и слух,
подключённые сервисы, автозапуск, место на диске, копии, ошибки за сутки, права.
Глубокая («проверь себя», кнопка «Проверить глубже») — настоящие крошечные запросы: каждый мозг отвечает одним словом,
голос Светланы, календарь, Telegram, телефон, остаток пакета Qwen. Значения ключей нигде не показываются.

Каждая проверка: {"area", "name", "level", "detail"}; level — ok / warn / fail / off (выключено намеренно).
"""
import concurrent.futures
import json
import os
import shutil
import subprocess
import time

from . import config
from .config import DATA

LEVELS = ("ok", "warn", "fail", "off")
ICON = {"ok": "✓", "warn": "!", "fail": "✗", "off": "–"}


def _started():
    """Когда запущен этот процесс Chloe (а не когда загрузился модуль)."""
    try:
        return os.stat("/proc/self").st_ctime
    except OSError:
        return time.time()


STARTED = _started()


def item(area, name, level, detail=""):
    return {"area": area, "name": name, "level": level, "detail": detail}


def _safe(area, name, fn):
    """Сломанная проверка — сама по себе ошибка, а не падение всей самопроверки."""
    try:
        out = fn()
        return out if isinstance(out, list) else [out]
    except Exception as e:
        return [item(area, name, "fail", "проверка не прошла: {}".format(type(e).__name__))]


# --- быстрые проверки ---
def safe():
    from . import safemode

    if not safemode.on():
        return []
    return item("Система", "Безопасный режим", "warn", "включён с {} — действия на паузе".format(
        time.strftime("%d.%m %H:%M", time.localtime(safemode.since() or time.time()))))


def brains():
    keys = {"Qwen": config.QWEN_KEY, "DeepSeek": config.DEEPSEEK_KEY, "Claude": config.ANTHROPIC_KEY, "Gemini": config.GEMINI_KEY}
    out = [item("Мозг", "Основной", "ok" if config.has_key() else "fail",
                "{} · быстрый {} · сильный {}".format(config.PROVIDER, config.MODEL_FAST, config.MODEL_STRONG)
                if config.has_key() else "нет ключа — Chloe не может думать")]
    have = [n for n, k in keys.items() if k]
    out.append(item("Мозг", "Ключи", "ok" if len(have) > 1 else "warn",
                    "есть: {}{}".format(", ".join(have) or "нет", "" if len(have) > 1 else " — запасного мозга нет")))
    try:
        from . import qwen_plan

        if config.QWEN_KEY and qwen_plan.exhausted():
            out.append(item("Мозг", "Пакет Qwen", "fail", "кредиты закончились — отвечаю через запасную модель"))
    except Exception:
        pass
    return out


def voice_ears():
    out = []
    piper = config.VOICES_DIR / (config.PIPER_VOICE + ".onnx")
    detail = {"edge": "Светлана (Microsoft, онлайн)", "piper": "Ирина (Piper, офлайн)", "qwen": "голос Qwen",
              "svetlana": "только Светлана"}.get(config.TTS, config.TTS)
    out.append(item("Голос", "Голос", "ok", detail + (", запасной — Ирина офлайн" if piper.exists() else "")))
    if config.TTS == "piper" and not piper.exists():
        out[-1] = item("Голос", "Голос", "fail", "офлайн-голос Piper не скачан: python run.py --install-voice")
    ears = config.EARS_DIR / config.EARS_MODEL
    if config.WAKE_OFFLINE:
        out.append(item("Слух", "Слово «Хлоя»", "ok" if ears.exists() else "warn",
                        "офлайн (Vosk)" if ears.exists() else "модель Vosk не скачана — слушаю через Google: python run.py --install-ears"))
    out.append(item("Слух", "Распознавание", "ok", {"google": "Google", "qwen": "Qwen"}.get(config.ASR, config.ASR)))
    return out


def services():
    out = []
    from . import google_calendar as gc

    if gc.connected():
        out.append(item("Сервисы", "Google Calendar", "ok", "подключён"))
    else:
        out.append(item("Сервисы", "Google Calendar", "off", "не подключён"))
    from .telegram import telegram

    out.append(item("Сервисы", "Telegram", "ok" if telegram.ready() else "off", "вход выполнен" if telegram.ready() else "не подключён"))
    if shutil.which("adb"):
        try:
            r = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=3).stdout
            ready = [l for l in r.splitlines()[1:] if l.strip().endswith("device")]
            out.append(item("Сервисы", "Телефон", "ok" if ready else "off", "подключён" if ready else "не подключён"))
        except (OSError, subprocess.SubprocessError):
            out.append(item("Сервисы", "Телефон", "warn", "adb не ответил"))
    else:
        out.append(item("Сервисы", "Телефон", "off", "adb не установлен"))
    out.append(item("Сервисы", "Bailian CLI", "ok" if shutil.which("bl") else "off",
                    "точный остаток Qwen" if shutil.which("bl") else "нет — остаток Qwen только в консоли"))
    return out


def system():
    out = []
    from . import autostart

    out.append(item("Система", "Автозапуск", "ok" if autostart.enabled() else "off",
                    "вместе с компьютером" if autostart.enabled() else "выключен"))
    free = shutil.disk_usage(str(config.HOME)).free / 2 ** 30
    out.append(item("Система", "Диск", "ok" if free > 5 else "warn" if free > 1 else "fail", "свободно {:.0f} ГБ".format(free)))
    from . import snapshots

    days = snapshots.days()
    today = time.strftime("%Y-%m-%d")
    days = sorted(days, key=lambda d: d[:10], reverse=True)
    out.append(item("Система", "Копии памяти", "ok" if days and days[0].startswith(today) else "warn",
                    "последняя {}, всего {}".format(days[0], len(days)) if days else "копий нет"))
    try:
        from .studio import ffmpeg

        ffmpeg()
        out.append(item("Система", "ffmpeg", "ok", "ролики и аудиокниги"))
    except Exception:
        out.append(item("Система", "ffmpeg", "warn", "нет — ролики и аудиокниги не соберутся"))
    try:
        from . import sandbox

        ok = sandbox.available()
        out.append(item("Система", "Песочница", "ok" if ok else "warn",
                        "команды проверяются пробой до выполнения" if ok else "проба недоступна — только разбор риска"))
    except Exception:
        out.append(item("Система", "Песочница", "warn", "не проверилась"))
    try:
        ver = subprocess.run(["git", "-C", str(_project()), "log", "-1",
                              "--format=%h %cd", "--date=format:%d.%m %H:%M"], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        ver = ""
    up = int(time.time() - STARTED)
    out.append(item("Система", "Версия", "ok", "{}{}работаю {}".format(ver, " · " if ver else "", _dur(up))))
    return out


def _project():
    import pathlib

    return pathlib.Path(__file__).resolve().parent.parent


def _dur(sec):
    if sec < 3600:
        return "{} мин".format(max(1, sec // 60))
    if sec < 86400:
        return "{} ч {} мин".format(sec // 3600, sec % 3600 // 60)
    return "{} дн {} ч".format(sec // 86400, sec % 86400 // 3600)


def errors(hours=24):
    """Ошибки инструментов за сутки из журнала (отказы пользователя — не ошибки)."""
    import sqlite3

    db = sqlite3.connect(str(config.JOURNAL_FILE), timeout=5)
    try:
        rows = db.execute("SELECT skill, detail FROM events WHERE kind = 'tool' AND ok = 0 AND ts > ?",
                          (time.time() - hours * 3600,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        db.close()
    real = {}
    for skill, detail in rows:
        try:
            data = json.loads(detail or "{}")
            if isinstance(data, str):              # записано строкой внутри JSON
                data = json.loads(data)
            result = str(data.get("result", "")) if isinstance(data, dict) else str(data)
        except ValueError:
            result = str(detail or "")
        if result.startswith(("Пользователь", "Не ", "Отказано")) and "Ошибка" not in result[:20]:
            continue      # «Пользователь отклонил», «Не публикую», «Отказано: приватная папка» — это работа защиты, а не поломка
        real.setdefault(skill or "?", []).append(result[:80])
    n = sum(len(v) for v in real.values())
    if not n:
        return item("Ошибки", "За сутки", "ok", "ошибок нет")
    worst = sorted(real.items(), key=lambda kv: -len(kv[1]))[:3]
    last = "; ".join("{}: {}".format(k, v[-1][:70]) for k, v in worst)
    return dict(item("Ошибки", "За сутки", "warn" if n < 10 else "fail",
                "{}: {}".format(n, ", ".join("{} ×{}".format(k, len(v)) for k, v in worst))), last=last)   # тексты ошибок — в отчёте для мозга


def rights():
    from .permissions import CATEGORIES, permissions

    strict = [CATEGORIES[k][0] + (" — запрещено" if permissions.level(k) == "block" else " — спрашивать")
              for k in CATEGORIES if permissions.level(k) != "allow"]
    vault = len(getattr(permissions, "vault", []) or [])
    detail = ("ограничено: " + ", ".join(strict) if strict else "всё по умолчанию") + (", приватных папок: {}".format(vault) if vault else "")
    return item("Права", "Карта прав", "ok", detail)


def safety():
    from .security import audit

    return audit()


FAST = (("Система", "Безопасный режим", safe), ("Мозг", "Мозг", brains), ("Голос", "Голос", voice_ears), ("Сервисы", "Сервисы", services),
        ("Система", "Система", system), ("Ошибки", "Ошибки", errors), ("Права", "Права", rights),
        ("Безопасность", "Безопасность", safety))


def quick():
    out = []
    for area, name, fn in FAST:
        out += _safe(area, name, fn)
    return out


# --- глубокие проверки: настоящие крошечные запросы ---
def ping_brains():
    out = []
    jobs = []
    if config.QWEN_KEY:
        from .thinking.openai_chat import qwen_base_url

        jobs.append(("Qwen", "openai", qwen_base_url(), config.QWEN_KEY, "qwen3.8-flash" if config.PROVIDER != "qwen" else config.MODEL_FAST))
    if config.DEEPSEEK_KEY:
        jobs.append(("DeepSeek", "openai", "https://api.deepseek.com", config.DEEPSEEK_KEY, "deepseek-chat"))
    if config.ANTHROPIC_KEY:
        jobs.append(("Claude", "anthropic", None, None, config.MIXED_STRONG or "claude-haiku-5-5"))

    def one(job):
        name, kind, base, key, model = job
        t = time.time()
        try:
            if kind == "openai":
                from openai import OpenAI

                OpenAI(base_url=base, api_key=key, timeout=20, max_retries=0).chat.completions.create(
                    model=model, max_tokens=3, messages=[{"role": "user", "content": "ок"}])
            else:
                import anthropic

                anthropic.Anthropic(timeout=20, max_retries=0).messages.create(
                    model=model, max_tokens=3, messages=[{"role": "user", "content": "ок"}])
            dt = time.time() - t
            return item("Мозг", name, "ok" if dt < 8 else "warn", "{} ответил за {:.1f} с".format(model, dt))
        except Exception as e:
            code = getattr(e, "status_code", None)
            why = {401: "ключ не принят", 402: "нет денег на счёте", 403: "доступ запрещён", 429: "лимит или кредиты кончились"}.get(
                code, type(e).__name__)
            return item("Мозг", name, "fail", "{}: {}".format(model, why))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        out = list(pool.map(one, jobs))
    return out


def ping_voice():
    from . import audiobook as ab

    attempts, ab.ATTEMPTS = ab.ATTEMPTS, 2          # проверка — не книга: две попытки, а не восемь
    try:
        t = time.time()
        ab._edge("Проверка.", config.VOICE, "+0%", timeout=15)
        return item("Голос", "Светлана", "ok", "отвечает за {:.1f} с".format(time.time() - t))
    except Exception:
        return item("Голос", "Светлана", "fail" if config.TTS in ("edge", "svetlana") else "warn",
                    "сервер Microsoft не отвечает — говорю запасным голосом")
    finally:
        ab.ATTEMPTS = attempts


def ping_calendar():
    from . import google_calendar as gc

    if not gc.connected():
        return item("Сервисы", "Google Calendar", "off", "не подключён")
    import datetime

    now = datetime.datetime.now(gc.local_tz())
    try:
        n = len(gc.events(now, now + datetime.timedelta(days=1)))
        return item("Сервисы", "Google Calendar", "ok", "отвечает, событий на сутки: {}".format(n))
    except gc.NotConnected as e:
        return item("Сервисы", "Google Calendar", "fail", "{} — скажите «подключи календарь»".format(e))


def ping_telegram():
    from .telegram import telegram

    if not telegram.ready():
        return item("Сервисы", "Telegram", "off", "не подключён")

    async def me(client):
        return await client.get_me()

    telegram.run(me, timeout=20)
    return item("Сервисы", "Telegram", "ok", "вход действует")


def ping_phone():
    from . import android

    try:
        i = android.info()
        return item("Сервисы", "Телефон", "ok", "{} {}, батарея {}%".format(i["maker"], i["model"], i["battery"]))
    except android.PhoneError as e:
        return item("Сервисы", "Телефон", "off", str(e)[:80])


def ping_credits():
    from . import qwen_plan

    if not config.QWEN_KEY:
        return []
    info = qwen_plan.from_cli(timeout=10)
    if not info:
        return item("Мозг", "Пакет Qwen", "off", "точный остаток — только в консоли Alibaba")
    p = info["percent"]
    return item("Мозг", "Пакет Qwen", "ok" if p < 0.8 else "warn" if p < 0.95 else "fail",
                "потрачено {:.1f} %{}".format(p * 100, qwen_plan._reset_text(info.get("reset"))))


def ping_internet():
    import requests

    t = time.time()
    requests.head("https://www.google.com/generate_204", timeout=6)
    return item("Система", "Интернет", "ok", "есть ({:.1f} с)".format(time.time() - t))


DEEP = (("Мозг", "Мозг", ping_brains), ("Голос", "Светлана", ping_voice), ("Сервисы", "Google Calendar", ping_calendar),
        ("Сервисы", "Telegram", ping_telegram), ("Сервисы", "Телефон", ping_phone), ("Мозг", "Пакет Qwen", ping_credits),
        ("Система", "Интернет", ping_internet))


def deep():
    """Быстрые проверки, где каждая из глубоких заменяет свою быструю (по названию)."""
    base = quick()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(DEEP)) as pool:
        results = list(pool.map(lambda d: _safe(d[0], d[1], d[2]), DEEP))
    found = [x for r in results for x in r]
    names = {(x["area"], x["name"]) for x in found}
    merged = [x for x in base if (x["area"], x["name"]) not in names]
    order = {a: i for i, a in enumerate(["Мозг", "Голос", "Слух", "Сервисы", "Система", "Ошибки", "Права", "Безопасность"])}
    return sorted(merged + found, key=lambda x: order.get(x["area"], 99))


def verdict(items):
    bad = [x for x in items if x["level"] == "fail"]
    warn = [x for x in items if x["level"] == "warn"]
    if bad:
        return "fail", "Есть поломки: " + "; ".join("{} — {}".format(x["name"], x["detail"]) for x in bad[:4])
    if warn:
        return "warn", "В целом работаю, но: " + "; ".join("{} — {}".format(x["name"], x["detail"]) for x in warn[:4])
    return "ok", "Всё работает."


def report(items):
    level, summary = verdict(items)
    lines = [summary]
    area = None
    for x in items:
        if x["area"] != area:
            area = x["area"]
            lines.append(area + ":")
        lines.append("  {} {} — {}".format(ICON[x["level"]], x["name"], x["detail"]))
        if x.get("last"):
            lines.append("    последние: " + x["last"])
    return "\n".join(lines)


def snapshot_file():
    return DATA / "state.json"


def save(items):
    """Последний результат — в файл: панель покажет его сразу, а журнал Self-Improvement потом сможет его разобрать."""
    try:
        snapshot_file().write_text(json.dumps({"at": time.time(), "items": items}, ensure_ascii=False), encoding="utf-8")
        os.chmod(snapshot_file(), 0o600)
    except OSError:
        pass
