"""Claude рядом с Qwen и DeepSeek: один запрос к Claude (официальная библиотека Anthropic) из общей истории.

История разговора в openai_chat.py — в формате OpenAI. Здесь она переводится в формат Claude перед запросом,
а ответ Claude — обратно. Ответ Claude хранится в истории ещё и как есть (поле "_anthropic"),
и Claude получает его неизменным: так модели можно менять посреди одной просьбы.

Для голоса скорость важнее глубины: раздумья выключены, effort — low.
"""
import json
import re
from types import SimpleNamespace as NS

from ..tools import TOOLS


class Refused(Exception):
    """Claude отказался отвечать (stop_reason refusal) — шаг сделает другая модель."""


def claude_args(model):
    """Раздумья и effort для голосового помощника."""
    if model.startswith("claude-sonnet-5-5"):
        return {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}   # disabled → 400
    if model.startswith("claude-haiku-5-5"):
        return {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}
    if model.startswith(("claude-opus-5-5", "claude-fable-5")):
        return {"output_config": {"effort": "low"}}   # раздумья не выключаются — только effort
    return {}


def safe_id(call_id):
    """У Claude id вызова — только буквы, цифры, _ и -."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(call_id or "call"))


def image_block(part):
    url = part["image_url"]["url"]
    m = re.match(r"data:([^;]+);base64,(.*)", url, re.S)
    if not m:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}}


def to_claude(messages):
    """(system, messages) в формате Claude из истории OpenAI."""
    system, out = "", []

    def add(role, blocks):
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"] += blocks
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        role, content = m["role"], m.get("content")
        if role == "system":
            system += (content or "") + "\n"
        elif role == "assistant":
            if m.get("_anthropic"):
                # ответ Claude — как есть, но без блоков раздумий: они привязаны к точной истории, а история
                # укорачивается (forget_old) и в ней убираются старые скриншоты — с ними Claude отвечает 400
                blocks = [b for b in m["_anthropic"] if b.get("type") not in ("thinking", "redacted_thinking")]
                add("assistant", blocks or [{"type": "text", "text": "…"}])
                continue
            blocks = [{"type": "text", "text": content}] if content else []
            for c in m.get("tool_calls") or []:
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                except ValueError:
                    args = {}
                blocks.append({"type": "tool_use", "id": safe_id(c["id"]), "name": c["function"]["name"],
                               "input": args if isinstance(args, dict) else {}})
            add("assistant", blocks or [{"type": "text", "text": "…"}])
        elif role == "tool":
            add("user", [{"type": "tool_result", "tool_use_id": safe_id(m["tool_call_id"]), "content": str(content or "")}])
        elif isinstance(content, list):
            blocks = []
            for part in content:
                if part.get("type") == "text":
                    blocks.append({"type": "text", "text": part["text"]})
                elif part.get("type") == "image_url":
                    blocks += [b for b in [image_block(part)] if b]
            add("user", blocks)
        else:
            add("user", [{"type": "text", "text": content or "…"}])
    if out and out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "…"}]})
    return system.strip(), out


def claude_tools(only=None):
    """only — имена инструментов (агенту даётся только его набор); None — все."""
    tools = [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in TOOLS
             if only is None or t["name"] in only]
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}   # инструменты и system кэшируются — каждый шаг дешевле
    return tools


def ask_claude(client, messages, model, tools=True, max_tokens=1500):
    """Запрос к Claude. Ответ — в том же виде, что у OpenAI (content, tool_calls), плюс исходные блоки Claude.
    Отказ модели (stop_reason refusal) — Refused: chat() перейдёт к запасной модели."""
    system, msgs = to_claude(messages)
    kw = {"model": model, "max_tokens": max_tokens, "messages": msgs, **claude_args(model)}
    if system:
        kw["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    if tools:
        kw["tools"] = claude_tools(tools if isinstance(tools, (set, list, tuple, frozenset)) else None)
    resp = client.messages.create(**kw)
    if resp.stop_reason == "refusal":
        raise Refused(model)
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    calls = [NS(id=b.id, function=NS(name=b.name, arguments=json.dumps(b.input, ensure_ascii=False)))
             for b in resp.content if b.type == "tool_use"]
    raw = [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else dict(b) for b in resp.content]
    return NS(content=text, tool_calls=calls or None, model_extra={}, anthropic_content=raw, usage=getattr(resp, "usage", None))
