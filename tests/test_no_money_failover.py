"""Кончились деньги у одного мозга — сразу отвечает другой: DeepSeek → Claude и Claude → DeepSeek. Сеть не нужна."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

import anthropic
import httpx
import openai

from chloe import config, usage
from chloe.thinking import openai_chat as oc


def answer(text):
    return NS(choices=[NS(message=NS(content=text, tool_calls=None, model_extra={}))], usage=None)


def http(code):
    return httpx.Response(code, request=httpx.Request("POST", "https://x"))


def deepseek_broke():
    return openai.APIStatusError("Error code: 402 - Insufficient Balance", response=http(402),
                                 body={"error": {"message": "Insufficient Balance"}})


def claude_broke():
    return anthropic.BadRequestError("Your credit balance is too low to access the Anthropic API.", response=http(400),
                                     body={"error": {"type": "invalid_request_error",
                                                     "message": "Your credit balance is too low to access the Anthropic API."}})


class FakeOpenAI:
    def __init__(self, replies):
        self.replies, self.models = list(replies), []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.models.append(kw["model"])
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class NoMoney(unittest.TestCase):
    def setUp(self):
        oc.cooldown.clear()
        oc._money_told.clear()
        self.addCleanup(mock.patch.stopall)
        for name, value in {"PROVIDER": "deepseek", "QWEN_KEY": None, "DEEPSEEK_KEY": "test", "ANTHROPIC_KEY": "test",
                            "GEMINI_KEY": None, "MODEL_FAST": "deepseek-flash", "MODEL_STRONG": "deepseek-v4-pro",
                            "MODEL_EYES": "claude-haiku-5-5"}.items():
            mock.patch.object(config, name, value, create=True).start()
        mock.patch.object(usage, "over_limit", return_value=None).start()
        mock.patch.object(usage, "from_openai").start()
        mock.patch.object(usage, "from_anthropic").start()
        self.journal = mock.patch("chloe.journal.journal").start()

    def test_detects_no_money_but_not_busy(self):
        self.assertTrue(oc.is_no_money(deepseek_broke()))
        self.assertTrue(oc.is_no_money(claude_broke()))
        busy = openai.APIStatusError("Rate limit", response=http(429), body={"error": {"message": "slow down"}})
        self.assertFalse(oc.is_no_money(busy))

    def test_deepseek_broke_claude_answers(self):
        ds = FakeOpenAI([deepseek_broke()])
        claude = mock.patch.object(oc, "ask_claude", return_value=NS(content="Ответ Claude", tool_calls=None, usage=None)).start()
        msg, model = oc.chat({"deepseek": ds, "anthropic": object()}, [{"role": "user", "content": "привет"}],
                             "deepseek-flash", tools=False)
        self.assertEqual(model, "claude-haiku-5-5")
        self.assertEqual(msg.content, "Ответ Claude")
        self.assertEqual(ds.models, ["deepseek-flash"])            # DeepSeek V4 Pro не пробуем — денег нет у всего DeepSeek
        claude.assert_called_once()
        self.assertGreater(oc.cooldown["deepseek-v4-pro"], 0)     # и сильный DeepSeek отдыхает
        self.journal.add.assert_called_once()                      # сказала в журнал, кто отвечает

    def test_next_request_goes_straight_to_claude(self):
        mock.patch.object(oc, "ask_claude", return_value=NS(content="ок", tool_calls=None, usage=None)).start()
        ds = FakeOpenAI([deepseek_broke()])
        oc.chat({"deepseek": ds, "anthropic": object()}, [{"role": "user", "content": "1"}], "deepseek-flash", tools=False)
        msg, model = oc.chat({"deepseek": ds, "anthropic": object()}, [{"role": "user", "content": "2"}],
                             "deepseek-flash", tools=False)
        self.assertEqual(model, "claude-haiku-5-5")
        self.assertEqual(ds.models, ["deepseek-flash"])            # второй раз DeepSeek даже не спрашиваем

    def test_claude_broke_deepseek_answers(self):
        mock.patch.object(oc, "ask_claude", side_effect=claude_broke()).start()
        ds = FakeOpenAI([answer("Ответ DeepSeek")])
        msg, model = oc.chat({"deepseek": ds, "anthropic": object()}, [{"role": "user", "content": "что на экране?"}],
                             "claude-haiku-5-5", tools=False)
        self.assertTrue(model.startswith("deepseek"))
        self.assertEqual(msg.content, "Ответ DeepSeek")
        self.assertGreater(oc.cooldown["claude-haiku-5-5"], 0)

    def test_everyone_broke_raises(self):
        mock.patch.object(oc, "ask_claude", side_effect=claude_broke()).start()
        ds = FakeOpenAI([deepseek_broke()])
        with self.assertRaises(Exception):
            oc.chat({"deepseek": ds, "anthropic": object()}, [{"role": "user", "content": "привет"}],
                    "deepseek-flash", tools=False)


if __name__ == "__main__":
    unittest.main()
