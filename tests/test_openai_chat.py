"""Qwen и DeepSeek: цикл инструментов, раздумья, картинки, запасная модель. Сеть и ключи не нужны — клиенты поддельные."""
import json
import os
import unittest
from types import SimpleNamespace as NS
from unittest import mock

import httpx
import openai

from chloe import config
from chloe.thinking import openai_chat as oc
from chloe.thinking.router import Route
from chloe.voice import voice

voice.enabled = False


def answer(text="", calls=(), reasoning=None):
    tool_calls = [NS(id="call_%d" % i, function=NS(name=n, arguments=json.dumps(a))) for i, (n, a) in enumerate(calls)] or None
    msg = NS(content=text, tool_calls=tool_calls, model_extra={"reasoning_content": reasoning} if reasoning else {})
    return NS(choices=[NS(message=msg)])


def busy(code=503):
    return openai.APIStatusError("занято", response=httpx.Response(code, request=httpx.Request("POST", "https://x")), body=None)


class FakeClient:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class OpenAIStyle(unittest.TestCase):
    def setUp(self):
        oc.cooldown.clear()
        self.addCleanup(mock.patch.stopall)
        for name, value in {"PROVIDER": "qwen", "QWEN_KEY": "test", "DEEPSEEK_KEY": "test",
                            "MODEL_FAST": "qwen3.8-flash", "MODEL_STRONG": "qwen3.8-flash+thinking"}.items():
            mock.patch.object(config, name, value).start()
        self.tools = []
        mock.patch.object(oc, "run_tool", self.fake_tool).start()

    def fake_tool(self, name, args):
        self.tools.append((name, args))
        if name == "screenshot":
            return [{"type": "text", "text": "Экран"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}], False, False
        return "Погода: +12", False, False

    def think(self, clients, text="какая погода?"):
        history = []
        return oc.think_openai(clients, history, text, Route(text)), history

    def test_auto_provider_prefers_qwen_then_deepseek(self):
        import importlib
        import os

        env = {k: v for k, v in os.environ.items() if k not in ("CHLOE_PROVIDER", "DASHSCOPE_API_KEY", "QWEN_API_KEY", "DEEPSEEK_API_KEY")}
        try:
            with mock.patch.dict(os.environ, dict(env, DASHSCOPE_API_KEY="x", DEEPSEEK_API_KEY="y", GEMINI_API_KEY="z"), clear=True):
                self.assertEqual(importlib.reload(config).PROVIDER, "qwen")
                self.assertEqual(config.MODEL_FAST, "qwen3.8-flash")
            with mock.patch.dict(os.environ, dict(env, DEEPSEEK_API_KEY="y", GEMINI_API_KEY="z"), clear=True):
                self.assertEqual(importlib.reload(config).PROVIDER, "deepseek")
                self.assertEqual(config.MODEL_STRONG, "deepseek-v4-pro")
        finally:
            mock.patch.stopall()
            importlib.reload(config)
            self.setUp()

    def test_tool_loop_and_answer(self):
        qwen = FakeClient([answer(calls=[("weather", {"city": "Ташкент"})]), answer("В Ташкенте +12.")])
        text, history = self.think({"qwen": qwen})
        self.assertEqual(text, "В Ташкенте +12.")
        self.assertEqual(self.tools, [("weather", {"city": "Ташкент"})])
        self.assertEqual(history[0]["role"], "system")
        tool_msg = [m for m in history if m["role"] == "tool"][0]
        self.assertEqual(tool_msg["tool_call_id"], "call_0")
        self.assertEqual(qwen.requests[0]["model"], "qwen3.8-flash")
        self.assertEqual(qwen.requests[0]["extra_body"], {"enable_thinking": False})   # быстрый — без раздумий
        self.assertEqual(qwen.requests[0]["tools"][0]["type"], "function")

    def test_strong_qwen_thinks_and_keeps_reasoning(self):
        qwen = FakeClient([answer(calls=[("screenshot", {})], reasoning="посмотрю на экран"), answer("На экране браузер.")])
        text, history = self.think({"qwen": qwen}, "что у меня на экране?")   # «экран» — сразу сильный мозг
        self.assertEqual(qwen.requests[0]["model"], "qwen3.8-flash")
        self.assertEqual(qwen.requests[0]["extra_body"], {"enable_thinking": True})
        self.assertEqual(qwen.requests[0]["reasoning_effort"], "low")
        self.assertEqual([m for m in history if m.get("tool_calls")][0]["reasoning_content"], "посмотрю на экран")
        # скриншот: ответ инструмента — текстом, картинка — следом сообщением пользователя
        i = next(i for i, m in enumerate(history) if m["role"] == "tool")
        self.assertEqual(history[i + 1]["role"], "user")
        self.assertTrue(history[i + 1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_busy_qwen_falls_back_to_deepseek_without_images(self):
        qwen = FakeClient([busy(503), busy(503)])
        deepseek = FakeClient([answer("Привет!")])
        text, _ = self.think({"qwen": qwen, "deepseek": deepseek}, "привет")
        self.assertEqual(text, "Привет!")
        self.assertEqual(deepseek.requests[0]["model"], "deepseek-flash")
        self.assertEqual(deepseek.requests[0]["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertIn("qwen3.8-flash", oc.cooldown)   # занятую модель какое-то время не трогаем
        # DeepSeek картинок не принимает — вместо них пометка
        msgs = oc.for_provider([{"role": "user", "content": [{"type": "text", "text": "Скриншот"},
                                                            {"type": "image_url", "image_url": {"url": "data:"}}]}], "deepseek")
        self.assertIsInstance(msgs[0]["content"], str)
        self.assertIn("не видит", msgs[0]["content"])

    def test_only_deepseek_key(self):
        mock.patch.object(config, "QWEN_KEY", None).start()
        mock.patch.object(config, "PROVIDER", "deepseek").start()
        self.assertEqual(oc.backups("deepseek-flash"), ["deepseek-flash", "deepseek-v4-pro"])

    def test_token_plan_key_uses_its_own_address(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("QWEN_BASE_URL", None)
            self.assertEqual(oc.qwen_base_url("sk-sp-abc"), oc.QWEN_TOKEN_PLAN_URL)
            self.assertEqual(oc.qwen_base_url("sk-abc"), oc.QWEN_PAYG_URL)
            os.environ["QWEN_BASE_URL"] = "https://example.test/v1"
            self.assertEqual(oc.qwen_base_url("sk-sp-abc"), "https://example.test/v1")

    def test_real_error_is_not_hidden(self):
        qwen = FakeClient([busy(401)])   # неверный ключ — не «занято», запасная не поможет скрыть проблему
        with self.assertRaises(openai.APIStatusError):
            self.think({"qwen": qwen}, "привет")

    def test_forget_old_keeps_system_and_drops_images(self):
        history = [{"role": "system", "content": "s"}]
        for i in range(30):
            history += [{"role": "user", "content": "просьба %d" % i}, {"role": "assistant", "content": "ок"},
                        {"role": "user", "content": [{"type": "text", "text": "Скриншот"}]}]
        oc.forget_old_openai(history)
        self.assertEqual(history[0]["role"], "system")
        self.assertLessEqual(len(history), 41)
        self.assertTrue(history[1]["content"].startswith("просьба"))
        self.assertFalse(any(isinstance(m["content"], list) for m in history))


# ---------- Claude рядом с DeepSeek ----------

class Block(NS):
    def model_dump(self, exclude_none=True):
        return {k: v for k, v in vars(self).items() if v is not None}


def claude_answer(text="", calls=(), stop="end_turn"):
    content = ([Block(type="text", text=text)] if text else []) + \
              [Block(type="tool_use", id="toolu_%d" % i, name=n, input=a) for i, (n, a) in enumerate(calls)]
    return NS(stop_reason="tool_use" if calls else stop, content=content)


def claude_busy(code=529):
    import anthropic
    import httpx2

    return anthropic.APIStatusError("перегружен", response=httpx2.Response(code, request=httpx2.Request("POST", "https://x")),
                                    body=None)


class FakeClaude:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.messages = NS(create=self.create)

    def create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=str)))   # снимок: история потом меняется
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class WithClaude(unittest.TestCase):
    """DeepSeek — быстрый мозг, Claude Sonnet — сильный (видит экран) и запасной."""
    fake_tool, think = OpenAIStyle.fake_tool, OpenAIStyle.think

    def setUp(self):
        OpenAIStyle.setUp(self)
        for name, value in {"PROVIDER": "deepseek", "QWEN_KEY": None, "ANTHROPIC_KEY": "test",
                            "MODEL_FAST": "deepseek-flash", "MODEL_STRONG": "claude-sonnet-5-5"}.items():
            mock.patch.object(config, name, value).start()

    def test_config_pairs_deepseek_with_claude(self):
        import importlib
        import os

        env = {k: v for k, v in os.environ.items()
               if k not in ("CHLOE_PROVIDER", "CHLOE_MODEL", "CHLOE_MODEL_STRONG", "DASHSCOPE_API_KEY", "QWEN_API_KEY")}
        try:
            with mock.patch.dict(os.environ, dict(env, DEEPSEEK_API_KEY="y", ANTHROPIC_API_KEY="z"), clear=True):
                c = importlib.reload(config)
                self.assertEqual((c.PROVIDER, c.MODEL_FAST, c.MODEL_STRONG), ("deepseek", "deepseek-flash", "claude-haiku-5-5"))
                self.assertIsNone(c.MODEL_EYES)   # сильный и так Haiku — отдельные «глаза» не нужны
            with mock.patch.dict(os.environ, dict(env, DEEPSEEK_API_KEY="y", ANTHROPIC_API_KEY="z",
                                                  CHLOE_MODEL_STRONG="claude-sonnet-5-5"), clear=True):
                c = importlib.reload(config)
                self.assertEqual((c.MODEL_STRONG, c.MODEL_EYES), ("claude-sonnet-5-5", "claude-haiku-5-5"))
            with mock.patch.dict(os.environ, dict(env, DEEPSEEK_API_KEY="y"), clear=True):
                env.pop("ANTHROPIC_API_KEY", None)
                c = importlib.reload(config)
                self.assertEqual(c.MODEL_STRONG, "deepseek-v4-pro")
        finally:
            mock.patch.stopall()
            importlib.reload(config)
            self.setUp()

    def test_simple_request_stays_on_deepseek(self):
        deepseek, claude = FakeClient([answer("Привет!")]), FakeClaude([])
        text, _ = self.think({"deepseek": deepseek, "anthropic": claude}, "привет")
        self.assertEqual(text, "Привет!")
        self.assertEqual(claude.requests, [])

    def test_screen_goes_to_claude_with_image_and_fast_settings(self):
        claude = FakeClaude([claude_answer(calls=[("screenshot", {})]), claude_answer("На экране браузер.")])
        deepseek = FakeClient([])
        text, history = self.think({"deepseek": deepseek, "anthropic": claude}, "что у меня на экране?")
        self.assertEqual(text, "На экране браузер.")
        first, second = claude.requests
        self.assertEqual(first["model"], "claude-sonnet-5-5")
        self.assertEqual(first["thinking"], {"type": "between_tools"})
        self.assertEqual(first["output_config"], {"effort": "low"})
        self.assertIn("cache_control", first["tools"][-1])
        self.assertTrue(first["system"][0]["text"])
        # второй шаг: результат инструмента и скриншот — в одном сообщении пользователя, картинкой
        last = second["messages"][-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual(last["content"][0]["type"], "tool_result")
        self.assertEqual(last["content"][0]["tool_use_id"], "toolu_0")
        self.assertIn("image", [b["type"] for b in last["content"]])
        self.assertEqual(second["messages"][-2]["content"][0]["type"], "tool_use")   # ответ Claude — как есть
        self.assertTrue(any(m.get("_anthropic") for m in history))
        # DeepSeek потом получает ту же историю — без служебных полей и без картинок
        clean = oc.for_provider(history, "deepseek")
        self.assertFalse(any(k.startswith("_") for m in clean for k in m))
        self.assertFalse(any(isinstance(m.get("content"), list) for m in clean))

    def test_claude_busy_or_refusing_falls_back_to_strong_deepseek(self):
        for trouble in (claude_busy(529), claude_answer(stop="refusal")):
            oc.cooldown.clear()
            claude, deepseek = FakeClaude([trouble]), FakeClient([answer("Утром зарядка, днём работа.")])
            text, _ = self.think({"deepseek": deepseek, "anthropic": claude}, "составь план на день")   # сложная просьба
            self.assertEqual(text, "Утром зарядка, днём работа.")
            self.assertEqual(deepseek.requests[0]["model"], "deepseek-v4-pro")   # сильный — сильным

    def test_deepseek_history_converts_for_claude(self):
        from chloe.thinking.claude_bridge import to_claude

        history = [{"role": "system", "content": "s"}, {"role": "user", "content": "погода?"},
                   {"role": "assistant", "content": "", "reasoning_content": "r",
                    "tool_calls": [{"id": "call:0/x", "type": "function", "function": {"name": "weather", "arguments": "{}"}}]},
                   {"role": "tool", "tool_call_id": "call:0/x", "content": "+12"},
                   {"role": "assistant", "content": "Плюс двенадцать."}, {"role": "user", "content": "спасибо"}]
        system, msgs = to_claude(history)
        self.assertEqual(system, "s")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user", "assistant", "user"])
        self.assertEqual(msgs[1]["content"][0]["id"], msgs[2]["content"][0]["tool_use_id"])
        self.assertRegex(msgs[1]["content"][0]["id"], r"^[A-Za-z0-9_-]+$")

    def test_haiku_and_opus_settings(self):
        from chloe.thinking.claude_bridge import claude_args

        self.assertEqual(claude_args("claude-haiku-5-5"), {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}})
        self.assertNotIn("thinking", claude_args("claude-opus-5-5"))   # у Opus 5.5 раздумья не выключаются


if __name__ == "__main__":
    unittest.main()
