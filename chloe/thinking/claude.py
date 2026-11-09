"""Мышление через Claude (Anthropic): история с кэшем промпта и циклом инструментов."""
from ..signals import STOPPED, interrupt
from ..brain import brain
from .router import NUDGE
from ..tools import TOOLS, run_tool
from .claude_bridge import claude_args
from .prompt import start_thinking, system_prompt
from ..vision import vision, wants_frame


def strip_old_images(messages):
    last_turn = max((i for i, m in enumerate(messages) if is_turn_start(m)), default=-1)
    for i, m in enumerate(messages):
        if m["role"] == "user" and isinstance(m["content"], list):
            if i != last_turn and any(isinstance(b, dict) and b.get("type") == "image" for b in m["content"]):
                m["content"] = [{"type": "text", "text": "[старый кадр экрана удалён]"} if isinstance(b, dict) and b.get("type") == "image" else b
                                for b in m["content"]]   # кадр постоянного зрения нужен только к своей просьбе
            for block in m["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                    block["content"] = [{"type": "text", "text": "[старый скриншот удалён]"} if c.get("type") == "image" else c
                                        for c in block["content"]]


def is_turn_start(m):
    """Сообщение пользователя, а не результаты инструментов."""
    return m["role"] == "user" and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])


def trim_history(messages, limit=40):
    while len(messages) > limit:
        messages.pop(0)
        while messages and not is_turn_start(messages[0]):
            messages.pop(0)


CACHE = {"type": "ephemeral"}
TOOLS[-1]["cache_control"] = CACHE   # инструменты и system кэшируются — каждый шаг дешевле и быстрее


def mark_cache(messages):
    """Ставит отметку кэша на конец истории и снимает прошлую (отметок может быть не больше четырёх)."""
    for m in messages:
        if m["role"] == "user":
            for b in m["content"]:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    messages[-1]["content"][-1]["cache_control"] = CACHE


def think_claude(client, messages, user_text, route):
    content = [{"type": "text", "text": start_thinking(user_text)}]
    frame = vision.fresh_frame() if wants_frame(user_text) else None
    if frame:   # постоянное зрение: что пользователь видит прямо сейчас
        import base64

        content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.standard_b64encode(frame).decode()}})
    messages.append({"role": "user", "content": content})
    had_error = False
    for _ in range(30):   # предохранитель от бесконечного цикла
        if interrupt.is_set():
            break
        mark_cache(messages)
        resp = client.messages.create(model=route.model, max_tokens=1500, tools=TOOLS, messages=messages,
                                      system=[{"type": "text", "text": system_prompt(), "cache_control": CACHE}],
                                      **claude_args(route.model))   # для голоса: без раздумий, effort low
        if interrupt.is_set():   # ответ пришёл после «стоп» — не выполняем его
            break
        if resp.stop_reason == "tool_use" and route.redo_for([b.name for b in resp.content if b.type == "tool_use"]):
            continue   # быстрый мозг взялся за сложное — этот шаг заново делает сильный
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        verdict = None if resp.stop_reason == "tool_use" else route.check_answer(text)
        if verdict == "redo":
            continue   # быстрый мозг ответил словами вместо действия — шаг заново делает сильный
        messages.append({"role": "assistant", "content": resp.content})
        if verdict == "nudge":
            messages.append({"role": "user", "content": [{"type": "text", "text": NUDGE}]})
            continue
        if resp.stop_reason != "tool_use":
            if not had_error:
                brain.success()
            return text
        results, step_failed = [], False
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if interrupt.is_set():
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": "Не выполнено: пользователь сказал «стоп».", "is_error": True})
                continue
            out, is_error, failed = run_tool(block.name, block.input)
            had_error, step_failed = had_error or failed, step_failed or failed
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": out, "is_error": is_error})
        messages.append({"role": "user", "content": results})
        route.after_step(step_failed)
        brain.state("thinking")
    else:
        return "Я остановилась: слишком много шагов подряд."
    # «стоп»: история заканчивается её репликой, чтобы следующая просьба начиналась как обычно
    messages.append({"role": "assistant", "content": [{"type": "text", "text": STOPPED}]})
    return None
