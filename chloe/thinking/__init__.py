"""Мышление: какая модель думает (Qwen, DeepSeek, Claude или Gemini) и общий вход для главного цикла."""
from anthropic import Anthropic

from .. import config
from ..config import GEMINI_KEY
from .claude import strip_old_images, think_claude, trim_history
from .gemini import forget_old_gemini, think_gemini
from .openai_chat import ask_short_openai, forget_old_openai, make_clients, think_openai
from .router import Route
from ..brain import brain
from ..experience import recalled
from ..journal import journal
from ..memory import memory
from ..signals import state


def think(client, messages, user_text):
    route = Route(user_text)   # быстрый или сильный мозг — решается по ходу
    state["task_used"] = []    # что Chloe передавала инструментам в этой просьбе
    state["task_failed"] = {}  # какие шаги в этой просьбе не сработали (чтобы не повторять их по кругу)
    brain.task()
    if config.PROVIDER in config.OPENAI_STYLE:
        answer = think_openai(client, messages, user_text, route)
    elif config.PROVIDER == "gemini":
        answer = think_gemini(client, messages, user_text, route)
    else:
        answer = think_claude(client, messages, user_text, route)
    show_recall(user_text, " ".join(state["task_used"]) + " " + (answer or ""))
    return answer


def show_recall(user_text, used_text):
    """Воспоминания, которые реально пригодились, загораются в мозге зелёным и пишутся в журнал."""
    for text in recalled(user_text, used_text, memory.items):
        brain.recall(text)
        journal.add("memory", "Память", "Вспомнила: " + text, {"text": text, "recall": True})


def forget_old(messages):
    if config.PROVIDER in config.OPENAI_STYLE:
        forget_old_openai(messages)
    elif config.PROVIDER == "gemini":
        forget_old_gemini(messages)
    else:
        strip_old_images(messages)
        trim_history(messages)


def make_client():
    if config.PROVIDER in config.OPENAI_STYLE:
        return make_clients()
    if config.PROVIDER == "gemini":
        from google import genai
        from google.genai import types

        # без долгих повторов: при перегрузке быстрее перейти на запасную модель
        return genai.Client(api_key=GEMINI_KEY, http_options=types.HttpOptions(
            timeout=25000,   # мс: зависшая модель не должна держать Chloe долго — лучше перейти на запасную
            retry_options=types.HttpRetryOptions(attempts=1)))   # повторы не нужны: есть запасные модели
    return Anthropic()


def ask_short(client, prompt):
    """Короткий ответ быстрой модели без инструментов (например, название темы во сне)."""
    if config.PROVIDER in config.OPENAI_STYLE:
        return ask_short_openai(client, prompt)
    if config.PROVIDER == "gemini":
        from google.genai import types

        from .gemini import gemini_generate

        cfg = types.GenerateContentConfig(max_output_tokens=40)
        resp = gemini_generate(client, [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])], cfg, config.MODEL_FAST)
        return "".join(p.text for p in (resp.candidates[0].content.parts or []) if p.text and not p.thought)
    resp = client.messages.create(model=config.MODEL_FAST, max_tokens=40, messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if b.type == "text")
