"""Мышление через Gemini (Google): те же инструменты и тот же мозг, другой формат истории.
Перегруженные модели и модели в лимите пропускаются — сразу берётся запасная."""
import base64
import re
import time

from ..brain import brain
from ..config import GEMINI_THINKING
from ..signals import STOPPED, interrupt
from .router import NUDGE
from ..tools import TOOLS, run_tool
from .prompt import start_thinking, system_prompt
from ..vision import vision, wants_frame


def gemini_config():
    from google.genai import types

    decls = [types.FunctionDeclaration(name=t["name"], description=t["description"],
                                       parameters_json_schema=t["input_schema"] if t["input_schema"]["properties"] else None)
             for t in TOOLS]
    return types.GenerateContentConfig(
        system_instruction=system_prompt(), max_output_tokens=1500,
        tools=[types.Tool(function_declarations=decls)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))


def gemini_result(call, out, is_error):
    """Ответ инструмента для Gemini; скриншот уходит картинкой внутри ответа."""
    from google.genai import types

    images = []
    if isinstance(out, list):
        images = [types.FunctionResponsePart.from_bytes(data=base64.standard_b64decode(c["source"]["data"]),
                                                        mime_type=c["source"]["media_type"])
                  for c in out if c["type"] == "image"]
        out = " ".join(c["text"] for c in out if c["type"] == "text")
    part = types.Part.from_function_response(name=call.name, response={"error" if is_error else "result": out},
                                             parts=images or None)
    part.function_response.id = call.id
    return part


GEMINI_FALLBACKS = ("gemini-3-flash-preview", "gemini-flash-lite-latest", "gemini-3.1-flash-lite")   # если основная перегружена


# модель, упёршаяся в лимит или перегруженная, какое-то время пропускается — не ждём её отказа на каждом шаге
gemini_cooldown = {}                       # модель → время, до которого её не трогаем
gemini_no_thinking = set()                 # модели, которые не принимают настройку раздумий
COOLDOWN = {429: 15 * 60, 500: 120, 503: 120, 504: 120}


def gemini_wait(e):
    """Сколько не трогать модель. Google сам пишет, когда можно снова (retryDelay):
    при минутном лимите это секунды, при дневном — до следующих суток."""
    text = str(e)
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", text)
    if m:
        return int(m.group(1)) + 1
    if e.code == 429 and "PerDay" in text:
        return COOLDOWN[429]
    return 60 if e.code == 429 else COOLDOWN[e.code]


def gemini_order(model):
    """Сначала нужная модель (быстрая или сильная), потом запасные; отдыхающие после отказа — пропускаем."""
    models = [model] + [m for m in GEMINI_FALLBACKS if m != model]
    now = time.time()
    ready = [m for m in models if gemini_cooldown.get(m, 0) <= now]
    # все отдыхают — пробуем ту, что освободится раньше
    return ready or sorted(models, key=lambda m: gemini_cooldown.get(m, 0))[:1]


def gemini_model_config(config, model):
    """Gemini 3: думать поменьше — для голосового помощника скорость важнее глубины."""
    from google.genai import types

    if model.startswith("gemini-3") and "lite" not in model and model not in gemini_no_thinking:
        return config.model_copy(update={"thinking_config": types.ThinkingConfig(thinking_level=GEMINI_THINKING)})
    return config


def gemini_generate(client, history, config, model):
    from google.genai import errors

    models = gemini_order(model)
    for i, model in enumerate(models):
        try:
            started = time.time()
            resp = client.models.generate_content(model=model, contents=history, config=gemini_model_config(config, model))
            print("[{} · {:.1f} с]".format(model, time.time() - started))
            return resp
        except errors.APIError as e:
            if e.code == 400 and "think" in str(e).lower() and model not in gemini_no_thinking:
                gemini_no_thinking.add(model)   # не поддерживает thinking_level — без него
                print("[{} не принимает thinking_level, повторяю без него]".format(model))
                return client.models.generate_content(model=model, contents=history, config=config)
            if e.code not in COOLDOWN:
                raise
            wait = gemini_wait(e)
            gemini_cooldown[model] = time.time() + wait
            if i == len(models) - 1:
                raise
            print("[{} занята ({}), пропускаю её на {} с, пробую {}]".format(model, e.code, wait, models[i + 1]))


def think_gemini(client, history, user_text, route):
    from google.genai import types

    parts = [types.Part.from_text(text=start_thinking(user_text))]
    frame = vision.fresh_frame() if wants_frame(user_text) else None
    if frame:   # постоянное зрение: что пользователь видит прямо сейчас
        parts.insert(0, types.Part.from_bytes(data=frame, mime_type="image/jpeg"))
    history.append(types.Content(role="user", parts=parts))
    config = gemini_config()
    had_error = False
    for _ in range(30):   # предохранитель от бесконечного цикла
        if interrupt.is_set():
            break
        resp = gemini_generate(client, history, config, route.model)
        if interrupt.is_set():   # ответ пришёл после «стоп» — не выполняем его
            break
        content = resp.candidates[0].content if resp.candidates else None
        if content is None or not content.parts:
            return "Не получилось ответить, попробуйте сказать иначе."
        calls = resp.function_calls
        if calls and route.redo_for([c.name for c in calls]):
            continue   # быстрый мозг взялся за сложное — этот шаг заново делает сильный
        text = "".join(p.text for p in content.parts if p.text and not p.thought).strip()
        verdict = None if calls else route.check_answer(text)
        if verdict == "redo":
            continue   # быстрый мозг ответил словами вместо действия — шаг заново делает сильный
        history.append(content)
        if verdict == "nudge":
            history.append(types.Content(role="user", parts=[types.Part.from_text(text=NUDGE)]))
            continue
        if not calls:
            if not had_error:
                brain.success()
            return text
        results, step_failed = [], False
        for call in calls:
            if interrupt.is_set():
                results.append(gemini_result(call, "Не выполнено: пользователь сказал «стоп».", True))
                continue
            out, is_error, failed = run_tool(call.name, dict(call.args or {}))
            had_error, step_failed = had_error or failed, step_failed or failed
            results.append(gemini_result(call, out, is_error))
        history.append(types.Content(role="user", parts=results))
        route.after_step(step_failed)
        brain.state("thinking")
    else:
        return "Я остановилась: слишком много шагов подряд."
    history.append(types.Content(role="model", parts=[types.Part.from_text(text=STOPPED)]))
    return None


def forget_old_gemini(history, limit=40):
    """Как strip_old_images и trim_history, но для истории Gemini."""
    last_turn = max((i for i, c in enumerate(history) if c.role == "user" and any(p.text for p in c.parts or [])), default=-1)
    for i, c in enumerate(history):
        if i != last_turn and c.role == "user" and any(getattr(p, "inline_data", None) for p in c.parts or []):
            c.parts = [p for p in c.parts if not getattr(p, "inline_data", None)]   # старые кадры постоянного зрения
        for p in c.parts or []:
            if p.function_response and p.function_response.parts:
                p.function_response.parts = None
                p.function_response.response = dict(p.function_response.response or {}, note="старый скриншот удалён")
    while len(history) > limit:
        history.pop(0)
        while history and not (history[0].role == "user" and any(p.text for p in history[0].parts or [])):
            history.pop(0)
