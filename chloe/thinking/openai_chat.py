"""Мышление через Qwen (QwenCloud) и DeepSeek (язык OpenAI Chat Completions), а с ключом Claude — и через Claude.

Те же инструменты, тот же мозг и те же два уровня (быстрый/сильный), что у Claude и Gemini.
Основной — тот, кого выбрал config.PROVIDER; второй (если есть его ключ) — запасной:
занятая, перегруженная или недоступная модель пропускается, шаг делает следующая.

Модель «X+thinking» — та же X, но с раздумьями (для сильного мозга Qwen).
Скриншоты видят Qwen и Claude; DeepSeek в API картинок не принимает — ему достаётся только текст.
С ключом Claude сильный мозг — Claude Sonnet (см. config.MIXED_STRONG), запросы к нему — claude_bridge.py.
"""
import base64
import os
import time

from .. import config, usage
from ..brain import brain
from ..signals import STOPPED, interrupt
from ..tools import TOOLS, run_tool
from .claude_bridge import Refused, ask_claude
from .prompt import start_thinking, system_prompt
from ..vision import vision, wants_frame
from .router import NUDGE

PROVIDERS = {
    # ключи QwenCloud привязаны к региону: Сингапур по умолчанию, другой регион — QWEN_BASE_URL
    "qwen": {"base_url": os.environ.get("QWEN_BASE_URL", "https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1"),
             "key": lambda: config.QWEN_KEY, "images": True},
    "deepseek": {"base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                 "key": lambda: config.DEEPSEEK_KEY, "images": False},
    "anthropic": {"key": lambda: config.ANTHROPIC_KEY, "images": True},   # официальная библиотека Anthropic
}
THINKING = "+thinking"
COOLDOWN = {429: 60, 500: 120, 502: 120, 503: 120, 504: 120, 529: 120}   # 529 — Claude перегружен
cooldown = {}   # модель → время, до которого её не трогаем


def provider_of(model):
    if model.startswith("claude"):
        return "anthropic"
    return "deepseek" if model.startswith("deepseek") else "qwen"


def make_clients():
    """{провайдер: клиент} — для всех, у кого есть ключ."""
    from openai import OpenAI

    clients = {}
    for name, p in PROVIDERS.items():
        if not p["key"]():
            continue
        if name == "anthropic":
            from anthropic import Anthropic

            clients[name] = Anthropic(api_key=p["key"](), timeout=30, max_retries=0)
        else:
            # gzip, а не brotli: со старой библиотекой Brotli (<1.2) ответ сервера не распаковывается
            clients[name] = OpenAI(api_key=p["key"](), base_url=p["base_url"], timeout=30, max_retries=0,
                                   default_headers={"Accept-Encoding": "gzip, deflate"})
    return clients


def request_args(model):
    """Имя модели для API и настройки раздумий. Для голосового помощника скорость важнее глубины."""
    name, thinking = (model[:-len(THINKING)], True) if model.endswith(THINKING) else (model, False)
    if provider_of(name) == "deepseek":
        # раздумья DeepSeek с инструментами требуют возвращать их текст в каждом запросе — без них проще и быстрее
        return name, {"extra_body": {"thinking": {"type": "disabled"}}}
    if thinking:
        return name, {"reasoning_effort": "low", "extra_body": {"enable_thinking": True}}
    return name, {"extra_body": {"enable_thinking": False}}


def backups(model):
    """Нужная модель, потом запасные (у кого есть ключ): для сильного мозга — сначала сильные, для быстрого — быстрые."""
    strong = model == config.MODEL_STRONG and model != config.MODEL_FAST
    if model == getattr(config, "MODEL_EYES", None):
        strong = True   # глаза заменяет тот, кто тоже видит экран, — сильный, а не быстрый DeepSeek
    providers = [config.PROVIDER] + [p for p in PROVIDERS if p != config.PROVIDER]
    same_tier = [(config.STRONG_DEFAULT if strong else config.FAST_DEFAULT)[p] for p in providers if config.has_key(p)]
    other_tier = [(config.FAST_DEFAULT if strong else config.STRONG_DEFAULT)[p] for p in providers if config.has_key(p)]
    order = [model, config.MODEL_STRONG if strong else config.MODEL_FAST] + same_tier + other_tier
    seen, out = set(), []
    for m in order:
        if m and m not in seen and m.split("+")[0][:4] in ("qwen", "deep", "clau") and config.has_key(provider_of(m)):
            seen.add(m)
            out.append(m)
    now = time.time()
    ready = [m for m in out if cooldown.get(m, 0) <= now]
    return ready or sorted(out, key=lambda m: cooldown.get(m, 0))[:1]


def tool_specs():
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}} for t in TOOLS]


def for_provider(messages, provider):
    """История для конкретного провайдера: без служебных полей ("_anthropic"), а DeepSeek не принимает картинки —
    вместо них пометка."""
    out = []
    for m in messages:
        if any(k.startswith("_") for k in m):
            m = {k: v for k, v in m.items() if not k.startswith("_")}
        if isinstance(m.get("content"), list) and not PROVIDERS[provider]["images"]:
            text = " ".join(c["text"] for c in m["content"] if c.get("type") == "text")
            m = dict(m, content=text + " [скриншот: эта модель картинки не видит]")
        out.append(m)
    return out


KEEP_IMAGES = 2


def keep_last_images(messages, keep=KEEP_IMAGES):
    """Модели нужны только свежие скриншоты: старые в этой же задаче заменяются пометкой.
    Иначе на пятом шаге уходит пять картинок — медленно и дорого. История не меняется — меняется копия запроса."""
    seen, out = 0, []
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"]):
            seen += 1
            if seen > keep:
                m = dict(m, content=[{"type": "text", "text": "[прошлый скриншот убран — смотри свежий ниже]"}])
        out.append(m)
    return list(reversed(out))


def chat(clients, messages, model, tools=True, max_tokens=1500):
    """Один запрос с запасными моделями. Возвращает (сообщение ответа, модель, которая ответила)."""
    import anthropic
    import openai

    messages = keep_last_images(messages)
    models = backups(model)
    for i, m in enumerate(models):
        provider = provider_of(m)
        try:
            started = time.time()
            if provider == "anthropic":
                msg = ask_claude(clients[provider], messages, m, tools=tools, max_tokens=max_tokens)
                usage.from_anthropic(m, getattr(msg, "usage", None), time.time() - started)
            else:
                name, extra = request_args(m)
                resp = clients[provider].chat.completions.create(
                    model=name, messages=for_provider(messages, provider), max_tokens=max_tokens,
                    **({"tools": tool_specs()} if tools else {}), **extra)
                msg = resp.choices[0].message
                usage.from_openai(m, getattr(resp, "usage", None), time.time() - started)
            print("[{} · {:.1f} с]".format(m, time.time() - started))
            return msg, m
        except (openai.APIStatusError, openai.APIConnectionError,
                anthropic.APIStatusError, anthropic.APIConnectionError, Refused) as e:
            code = getattr(e, "status_code", None)
            refused = isinstance(e, Refused)   # Claude отказался — пусть ответит другая модель
            if code is not None and code not in COOLDOWN or refused and i == len(models) - 1:
                raise
            wait = 0 if refused else COOLDOWN.get(code, 60)
            cooldown[m] = time.time() + wait
            if i == len(models) - 1:
                raise
            print("[{} недоступна ({}), пропускаю её на {} с, пробую {}]".format(m, code or ("отказ" if refused else "нет связи"), wait, models[i + 1]))


def as_history(msg):
    """Ответ модели — в историю; текст раздумий сохраняем: Qwen и DeepSeek просят возвращать его вместе с инструментами."""
    entry = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        entry["tool_calls"] = [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                               for c in msg.tool_calls]
    if getattr(msg, "anthropic_content", None):
        entry["_anthropic"] = msg.anthropic_content   # Claude получит свой ответ неизменным
    reasoning = getattr(msg, "reasoning_content", None) or (getattr(msg, "model_extra", None) or {}).get("reasoning_content")
    if reasoning:
        entry["reasoning_content"] = reasoning
    return entry


def tool_messages(call_id, out):
    """Результат инструмента. Картинку (скриншот) в ответ инструмента не положить — она идёт следом от пользователя."""
    if not isinstance(out, list):
        return [{"role": "tool", "tool_call_id": call_id, "content": str(out)}]
    text = " ".join(c["text"] for c in out if c["type"] == "text") or "Скриншот ниже."
    images = [{"type": "image_url", "image_url": {"url": "data:{};base64,{}".format(c["source"]["media_type"], c["source"]["data"])}}
              for c in out if c["type"] == "image"]
    msgs = [{"role": "tool", "tool_call_id": call_id, "content": text}]
    if images:
        msgs.append({"role": "user", "content": [{"type": "text", "text": "Скриншот к результату инструмента:"}] + images})
    return msgs


def parse_args(raw):
    import json

    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {}
    except ValueError:
        return {}


def think_openai(clients, messages, user_text, route):
    if not messages or messages[0].get("role") != "system":
        messages.insert(0, {"role": "system", "content": ""})
    messages[0]["content"] = system_prompt()   # память и навыки могли измениться
    text = start_thinking(user_text)
    frame = vision.fresh_frame() if PROVIDERS[provider_of(route.model)]["images"] and wants_frame(user_text) else None
    if frame:   # постоянное зрение: что пользователь видит прямо сейчас
        messages.append({"role": "user", "_vision": True, "content": [   # _vision: служебная пометка, в модель не уходит
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.standard_b64encode(frame).decode()}}]})
    else:
        messages.append({"role": "user", "content": text})
    had_error = False
    for _ in range(30):   # предохранитель от бесконечного цикла
        if interrupt.is_set():
            break
        msg, _model = chat(clients, messages, route.model)
        if interrupt.is_set():   # ответ пришёл после «стоп» — не выполняем его
            break
        calls = msg.tool_calls or []
        if calls and route.redo_for([c.function.name for c in calls]):
            continue   # быстрый мозг взялся за сложное — этот шаг заново делает сильный
        text = (msg.content or "").strip()
        verdict = None if calls else route.check_answer(text)
        if verdict == "redo":
            continue
        messages.append(as_history(msg))
        if verdict == "nudge":
            messages.append({"role": "user", "content": NUDGE})
            continue
        if not calls:
            if not had_error:
                brain.success()
            return text or "Не получилось ответить, попробуйте сказать иначе."
        results, step_failed = [], False
        for call in calls:
            if interrupt.is_set():
                results += tool_messages(call.id, "Не выполнено: пользователь сказал «стоп».")
                continue
            out, is_error, failed = run_tool(call.function.name, parse_args(call.function.arguments))
            had_error, step_failed = had_error or failed, step_failed or failed
            results += tool_messages(call.id, ("Ошибка: " + str(out)) if is_error and not isinstance(out, list) else out)
        # сначала все ответы инструментов, потом картинки — так требует формат OpenAI
        messages += [m for m in results if m["role"] == "tool"] + [m for m in results if m["role"] != "tool"]
        route.after_step(step_failed)
        brain.state("thinking")
    else:
        return "Я остановилась: слишком много шагов подряд."
    messages.append({"role": "assistant", "content": STOPPED})
    return None


def forget_old_openai(messages, limit=40):
    """Старые скриншоты — убрать, длинную историю — укоротить (начиная с просьбы пользователя)."""
    for m in messages:
        if m["role"] == "user" and isinstance(m.get("content"), list):
            if m.pop("_vision", False):   # просьба с кадром постоянного зрения: слова остаются, картинка уходит
                m["content"] = " ".join(c["text"] for c in m["content"] if c.get("type") == "text") + " [кадр экрана удалён]"
            else:
                m["content"] = "[старый скриншот удалён]"
    system = messages[:1] if messages and messages[0]["role"] == "system" else []
    rest = messages[len(system):]
    while len(rest) > limit:
        rest.pop(0)
        while rest and not (rest[0]["role"] == "user" and isinstance(rest[0].get("content"), str)
                            and not rest[0]["content"].startswith("[старый скриншот")):
            rest.pop(0)
    messages[:] = system + rest


def ask_short_openai(clients, prompt):
    msg, _ = chat(clients, [{"role": "user", "content": prompt}], config.MODEL_FAST, tools=False, max_tokens=40)
    return msg.content or ""
