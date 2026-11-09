"""Кредиты Qwen Token Plan: пакет исчерпан → один раз сказать, отвечать через запасную, потом вернуться. Сеть не нужна."""
import json
import time
import unittest
from unittest import mock

import httpx
import openai

from chloe import config, qwen_plan, usage
from chloe.settings import settings
from chloe.thinking import openai_chat as oc
from chloe.voice import voice

voice.enabled = False


def err(code, body):
    req = httpx.Request("POST", "https://x/v1/chat/completions")
    return openai.APIStatusError("Error code: {} - {}".format(code, json.dumps(body)), response=httpx.Response(code, request=req),
                                 body=body)


QUOTA = err(429, {"error": {"code": "insufficient_quota", "message": "Your token-plan quota has been exhausted."}})
SLOW = err(429, {"error": {"code": "Throttling.RateQuota", "message": "Requests rate limit exceeded"}})


def answer(text="ок"):
    msg = mock.Mock(content=text, tool_calls=None)
    return mock.Mock(choices=[mock.Mock(message=msg)], usage=None)


class Detect(unittest.TestCase):
    def test_quota_vs_rate_limit(self):
        self.assertTrue(qwen_plan.is_quota_error(QUOTA))
        self.assertFalse(qwen_plan.is_quota_error(SLOW))
        self.assertFalse(qwen_plan.is_quota_error(err(500, {"error": {"message": "insufficient_quota"}})))


class FallBack(unittest.TestCase):
    def setUp(self):
        settings.set("qwen_plan", {})
        self.addCleanup(settings.set, "qwen_plan", {})
        oc.cooldown.clear()
        self.addCleanup(oc.cooldown.clear)
        p = [mock.patch.object(config, "PROVIDER", "qwen"), mock.patch.object(config, "MODEL_FAST", "qwen3.8-flash"),
             mock.patch.object(config, "MODEL_STRONG", "claude-haiku-5-5"),
             mock.patch.object(config, "has_key", lambda p: p in ("qwen", "deepseek"))]
        for x in p:
            x.start()
            self.addCleanup(x.stop)
        self.said = []
        mock.patch.object(voice, "say", side_effect=self.said.append).start()
        self.addCleanup(mock.patch.stopall)

    def clients(self, qwen):
        ds = mock.Mock()
        ds.chat.completions.create.return_value = answer("через deepseek")
        q = mock.Mock()
        q.chat.completions.create.side_effect = qwen
        return {"qwen": q, "deepseek": ds}

    def test_exhausted_once_then_skipped_then_back(self):
        c = self.clients(QUOTA)
        msg, model = oc.chat(c, [{"role": "user", "content": "привет"}], "qwen3.8-flash", tools=False)
        self.assertTrue(model.startswith("deepseek"))
        self.assertTrue(qwen_plan.exhausted())
        self.assertEqual(len([s for s in self.said if "Кредиты Qwen закончились" in s]), 1)
        self.assertIn("DeepSeek", self.said[0])
        # следующий запрос — Qwen даже не пробуем, и второй раз не объявляем
        calls = c["qwen"].chat.completions.create.call_count
        oc.chat(c, [{"role": "user", "content": "ещё"}], "qwen3.8-flash", tools=False)
        self.assertEqual(c["qwen"].chat.completions.create.call_count, calls)
        self.assertEqual(len(self.said), 1)
        # через 6 часов Qwen снова отвечает — отметка снимается
        s = settings.get("qwen_plan")
        s["exhausted_at"] = time.time() - qwen_plan.RETRY_AFTER - 1
        settings.set("qwen_plan", s)
        oc.cooldown.clear()
        c["qwen"].chat.completions.create.side_effect = None
        c["qwen"].chat.completions.create.return_value = answer("qwen снова")
        msg, model = oc.chat(c, [{"role": "user", "content": "снова"}], "qwen3.8-flash", tools=False)
        self.assertTrue(model.startswith("qwen"))
        self.assertNotIn("exhausted_at", settings.get("qwen_plan"))

    def test_plain_rate_limit_is_not_quota(self):
        c = self.clients(SLOW)
        oc.chat(c, [{"role": "user", "content": "привет"}], "qwen3.8-flash", tools=False)
        self.assertFalse(qwen_plan.exhausted())
        self.assertEqual(self.said, [])


class Report(unittest.TestCase):
    def setUp(self):
        settings.set("qwen_plan", {})
        self.addCleanup(settings.set, "qwen_plan", {})

    def test_month_usage_counts_only_qwen_this_month(self):
        month = time.strftime("%Y-%m")
        data = {month + "-01": {"qwen3.8-flash": {"calls": 3, "in": 100, "cached": 10, "written": 0, "out": 40},
                                "deepseek-flash": {"calls": 5, "in": 999, "cached": 0, "written": 0, "out": 1}},
                "2000-01-01": {"qwen3.8-flash": {"calls": 9, "in": 9, "cached": 0, "written": 0, "out": 9}}}
        with mock.patch.object(usage, "load", return_value=data):
            self.assertEqual(qwen_plan.month_usage(), {"calls": 3, "tokens": 150})

    def test_cli_parse_and_warn_once_per_level(self):
        info = qwen_plan.parse_cli({"hasQuotaData": True, "windows": [{"per1MonthPercentage": 0.83, "per1MonthResetTime": 1796083200000}]})
        self.assertAlmostEqual(info["percent"], 0.83)
        self.assertEqual(info["reset"], 1796083200)
        self.assertIn("83 %", qwen_plan.warning(info))
        self.assertIsNone(qwen_plan.warning(info))                                  # второй раз — молчим
        self.assertIn("96 %", qwen_plan.warning(dict(info, percent=0.96)))          # новый порог — говорим
        self.assertIsNone(qwen_plan.parse_cli({"hasQuotaData": False}))
        self.assertIsNone(qwen_plan.warning({"percent": 0.5, "reset": None}))

    def test_tool_without_cli(self):
        from chloe.tools import run_tool
        with mock.patch("shutil.which", return_value=None):
            out, _, _ = run_tool("qwen_credits", {})
        self.assertIn("только в консоли", out)
        self.assertIn("С начала месяца", out)

    def test_startup_says_when_exhausted(self):
        from chloe.app import startup_notices
        with mock.patch.object(config, "QWEN_KEY", "sk-sp-x"), mock.patch("shutil.which", return_value=None):
            self.assertEqual(startup_notices(), "")
            qwen_plan.mark_exhausted()
            self.assertIn("Кредиты Qwen закончились", startup_notices())


if __name__ == "__main__":
    unittest.main()
