"""Сколько стоит мышление: токены и деньги по каждой модели за день — чтобы деньги не уходили зря.

Цены — за 1 млн токенов, в долларах (DeepSeek: днём по UTC в часы пик вдвое дороже). Это оценка по прайсу,
точный счёт — в кабинетах console.anthropic.com и platform.deepseek.com. Хранится в ~/.chloe/usage.json.
"""
import json
import threading
import time

from .config import DATA

FILE = DATA / "usage.json"
# модель: (вход, вход из кэша, запись в кэш, выход)
PRICES = {
    "claude-haiku-5-5": (0.10, 0.01, 0.125, 0.50),
    "claude-sonnet-5-5": (2.00, 0.20, 2.50, 10.00),
    "claude-opus-5-5": (4.00, 0.20, 5.00, 20.00),
    "deepseek-flash": (0.15, 0.003, 0.15, 0.60),       # вне пика; в пик ×2
    "deepseek-v4-pro": (0.66, 0.022, 0.66, 1.98),
}
lock = threading.Lock()


def deepseek_peak(now=None):
    t = time.gmtime(now or time.time())
    return t.tm_wday < 5 and (1 <= t.tm_hour < 4 or 6 <= t.tm_hour < 10)


def cost(model, inp, cached, written, out, now=None):
    base = model.split("+")[0]
    p = PRICES.get(base)
    if p is None:
        return 0.0
    k = 2 if base.startswith("deepseek") and deepseek_peak(now) else 1
    return k * (inp * p[0] + cached * p[1] + written * p[2] + out * p[3]) / 1e6


def load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}


def record(model, inp=0, out=0, cached=0, written=0, seconds=0.0):
    """Один запрос к модели. inp — вход без кэша."""
    day = time.strftime("%Y-%m-%d")
    with lock:
        data = load()
        m = data.setdefault(day, {}).setdefault(model, {"calls": 0, "in": 0, "cached": 0, "written": 0, "out": 0,
                                                        "usd": 0.0, "seconds": 0.0})
        m["calls"] += 1
        m["in"] += inp
        m["cached"] += cached
        m["written"] += written
        m["out"] += out
        m["usd"] = round(m["usd"] + cost(model, inp, cached, written, out), 6)
        m["seconds"] = round(m["seconds"] + seconds, 1)
        for old in sorted(data)[:-60]:   # храним два месяца
            data.pop(old)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.replace(FILE)


def from_openai(model, usage, seconds):
    if usage is None:
        return
    cached = getattr(usage, "prompt_cache_hit_tokens", None)
    if cached is None:   # Qwen и другие — как у OpenAI
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
    record(model, inp=max(0, (usage.prompt_tokens or 0) - cached), out=usage.completion_tokens or 0, cached=cached,
           seconds=seconds)


def from_anthropic(model, usage, seconds):
    if usage is None:
        return
    record(model, inp=usage.input_tokens or 0, out=usage.output_tokens or 0,
           cached=getattr(usage, "cache_read_input_tokens", 0) or 0,
           written=getattr(usage, "cache_creation_input_tokens", 0) or 0, seconds=seconds)


def tool_brain_usage(a):
    days = max(1, min(int(a.get("days") or 1), 60))
    data = load()
    picked = sorted(data)[-days:]
    total, per = 0.0, {}
    for day in picked:
        for model, m in data[day].items():
            agg = per.setdefault(model, {"calls": 0, "usd": 0.0, "seconds": 0.0, "tokens": 0})
            agg["calls"] += m["calls"]
            agg["usd"] += m["usd"]
            agg["seconds"] += m["seconds"]
            agg["tokens"] += m["in"] + m["cached"] + m["written"] + m["out"]
            total += m["usd"]
    if not per:
        return "Пока нет данных о расходах — учёт начался с этой версии."
    lines = ["{}: запросов {}, токенов {}, ≈${:.3f}, в среднем {:.1f} с на запрос".format(
        model, a_["calls"], a_["tokens"], a_["usd"], a_["seconds"] / max(1, a_["calls"]))
        for model, a_ in sorted(per.items(), key=lambda kv: -kv[1]["usd"])]
    period = "сегодня" if days == 1 else "за {} дн.".format(days)
    return "Расходы на мышление {} (оценка по прайсу; точно — в кабинетах Anthropic и DeepSeek): всего ≈${:.3f}.\n{}".format(
        period, total, "\n".join(lines))
