"""Кредиты подписки Qwen Token Plan (ключ sk-sp-…): сколько потрачено и что делать, когда пакет закончился.

Остаток пакета Alibaba отдаёт только через консоль (вход в аккаунт Alibaba Cloud), а не по ключу API. Поэтому:
- Chloe сама считает токены Qwen за месяц (из ~/.chloe/usage.json);
- если установлен Bailian CLI (`bl`) и выполнен `bl auth login --console`, берёт точный процент и дату сброса;
- ответ 429 «insufficient_quota» — пакет исчерпан: Chloe говорит об этом один раз, переходит на запасную модель
  (DeepSeek или Claude) и пробует Qwen снова через несколько часов. Первый успешный ответ Qwen снимает отметку.
"""
import json
import shutil
import subprocess
import threading
import time

from . import usage
from .settings import settings

RETRY_AFTER = 6 * 3600     # пакет закончился — не дёргаем Qwen 6 часов (потом пробуем: вдруг докупили или сбросился)
WARN_AT = (0.8, 0.95)       # предупреждать при 80 % и 95 % (если известен точный процент из Bailian CLI)
_lock = threading.Lock()


def is_quota_error(e):
    """429 «пакет исчерпан» — в отличие от обычного 429 «слишком часто»."""
    if getattr(e, "status_code", None) != 429:
        return False
    text = str(getattr(e, "message", "") or e).lower()
    body = getattr(e, "body", None)
    if body:
        text += " " + json.dumps(body, ensure_ascii=False).lower()
    return any(w in text for w in ("insufficient_quota", "quota has been exhausted", "quota exhausted",
                                   "token-plan quota", "arrearage", "allocated quota exceeded"))


def state():
    return settings.get("qwen_plan") or {}


def exhausted(now=None):
    at = state().get("exhausted_at")
    return bool(at) and (now or time.time()) - at < RETRY_AFTER


def mark_exhausted():
    """Возвращает True, если это новость (о ней надо сказать пользователю один раз)."""
    with _lock:
        s = state()
        fresh = not exhausted()
        s["exhausted_at"] = time.time()
        settings.set("qwen_plan", s)
        return fresh


def mark_ok():
    with _lock:
        s = state()
        if s.get("exhausted_at"):
            s.pop("exhausted_at")
            s["restored_at"] = time.time()
            settings.set("qwen_plan", s)
            return True
    return False


def month_usage(now=None):
    """Токены и запросы Qwen с начала текущего месяца (по учёту Chloe)."""
    month = time.strftime("%Y-%m", time.localtime(now or time.time()))
    calls = tokens = 0
    for day, models in usage.load().items():
        if not day.startswith(month):
            continue
        for model, m in models.items():
            if model.startswith("qwen"):
                calls += m.get("calls", 0)
                tokens += m.get("in", 0) + m.get("cached", 0) + m.get("written", 0) + m.get("out", 0)
    return {"calls": calls, "tokens": tokens}


def from_cli(timeout=20):
    """Точные данные из Bailian CLI: {"percent": 0..1, "reset": epoch} или None, если CLI нет или он не вошёл."""
    exe = shutil.which("bl")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "usage", "token-plan", "--output", "json"], capture_output=True, text=True,
                             timeout=timeout).stdout
        data = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return parse_cli(data)


def parse_cli(data):
    """Ищем долю использования и время сброса в любом месте ответа (формат CLI может меняться)."""
    found = {}

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                kl = k.lower()
                if "percent" in kl and isinstance(v, (int, float)) and "percent" not in found:
                    found["percent"] = v / 100 if v > 1 else v
                elif "reset" in kl and isinstance(v, (int, float)) and "reset" not in found:
                    found["reset"] = v / 1000 if v > 1e11 else v
                elif kl == "hasquotadata" and v is False:
                    found["none"] = True
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
    if found.get("none") or "percent" not in found:
        return None
    return {"percent": float(found["percent"]), "reset": found.get("reset")}


def warning(info, now=None):
    """Предупреждение о пакете (один раз на каждый порог за период) или None."""
    if not info:
        return None
    s = state()
    period = str(info.get("reset") or time.strftime("%Y-%m", time.localtime(now or time.time())))
    passed = [t for t in WARN_AT if info["percent"] >= t]
    if not passed:
        return None
    level = max(passed)
    if s.get("warned_period") == period and s.get("warned_level", 0) >= level:
        return None
    s.update(warned_period=period, warned_level=level)
    settings.set("qwen_plan", s)
    return "Кредиты Qwen Token Plan потрачены на {:.0f} %{}.".format(info["percent"] * 100, _reset_text(info.get("reset")))


def _reset_text(reset):
    if not reset:
        return ""
    return ", пакет обновится {}".format(time.strftime("%d.%m в %H:%M", time.localtime(reset)))


def status_text():
    lines = []
    if exhausted():
        lines.append("Пакет Qwen Token Plan исчерпан (Alibaba ответила «insufficient_quota»): сейчас отвечаю через запасную "
                     "модель. Снова попробую Qwen через несколько часов; докупить — в консоли Alibaba Cloud Model Studio → Token Plan.")
    info = from_cli()
    if info:
        lines.append("Пакет Qwen Token Plan потрачен на {:.0f} %{}.".format(info["percent"] * 100, _reset_text(info.get("reset"))))
    else:
        lines.append("Точный остаток пакета Alibaba показывает только в консоли (Model Studio → Token Plan) "
                     "или через Bailian CLI после «bl auth login --console».")
    m = month_usage()
    lines.append("С начала месяца через Qwen: {} запросов, {} токенов (мой учёт).".format(m["calls"], "{:,}".format(m["tokens"]).replace(",", " ")))
    return "\n".join(lines)
