"""Gemini: занятые модели пропускаются на столько, сколько просит Google; история после «стоп» корректна."""
import types as T
import unittest

from google.genai import errors, types

from chloe import config
from chloe.signals import STOPPED, interrupt
from chloe.thinking import gemini, think
from chloe.tools import HANDLERS
from chloe.voice import voice

voice.enabled = False

MINUTE = {"error": {"code": 429, "message": "Please retry in 37.2s.", "status": "RESOURCE_EXHAUSTED",
                    "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}}
DAY = {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED",
                 "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}


class Wait(unittest.TestCase):
    def test_wait_from_google(self):
        self.assertEqual(gemini.gemini_wait(errors.ClientError(429, MINUTE)), 38)
        self.assertEqual(gemini.gemini_wait(errors.ClientError(429, DAY)), 900)
        self.assertEqual(gemini.gemini_wait(errors.ServerError(503, {"error": {"code": 503, "message": "x"}})), 120)


class Order(unittest.TestCase):
    def test_busy_model_is_skipped_next_time(self):
        gemini.gemini_cooldown.clear()
        log = []

        class Models:
            def generate_content(self, model, contents, config):
                log.append((model, getattr(config.thinking_config, "thinking_level", None)))
                if model in ("gemini-3.5-flash", "gemini-3-flash-preview"):
                    raise errors.ClientError(429, MINUTE)
                return "ok"

        client = T.SimpleNamespace(models=Models())
        gemini.gemini_generate(client, [], types.GenerateContentConfig(), "gemini-3.5-flash")
        self.assertEqual([m for m, _ in log], ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-flash-lite-latest"])
        self.assertIsNotNone(log[0][1])   # Gemini 3 думает меньше — быстрее отвечает
        log.clear()
        gemini.gemini_generate(client, [], types.GenerateContentConfig(), "gemini-3.5-flash")
        self.assertEqual([m for m, _ in log], ["gemini-flash-lite-latest"])   # сразу к рабочей


class StopHistory(unittest.TestCase):
    def test_stop_keeps_history_valid(self):
        config.PROVIDER = "gemini"
        config.MODEL_FAST = config.MODEL_STRONG = "gemini-flash-lite-latest"
        gemini.gemini_cooldown.clear()
        calls = {"n": 0}

        class Models:
            def generate_content(self, model, contents, config):
                calls["n"] += 1
                fc = [types.FunctionCall(name="system_info", args={}, id="a%d" % calls["n"]),
                      types.FunctionCall(name="list_folder", args={"path": "~"}, id="b%d" % calls["n"])]
                content = types.Content(role="model", parts=[types.Part(function_call=f) for f in fc])
                return T.SimpleNamespace(candidates=[T.SimpleNamespace(content=content)], function_calls=fc)

        real = HANDLERS["system_info"]

        def info(a):
            if calls["n"] == 2:
                interrupt.set()
            return real(a)

        HANDLERS["system_info"] = info
        try:
            interrupt.clear()
            history = []
            self.assertIsNone(think(T.SimpleNamespace(models=Models()), history, "много шагов"))
        finally:
            HANDLERS["system_info"] = real
            interrupt.clear()
            config.PROVIDER = "anthropic"
        self.assertEqual([c.role for c in history], ["user", "model", "user", "model", "user", "model"])
        self.assertIn("error", history[-2].parts[1].function_response.response)
        self.assertEqual(history[-1].parts[0].text, STOPPED)


if __name__ == "__main__":
    unittest.main()
