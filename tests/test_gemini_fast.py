"""Бесплатный Gemini — быстрый мозг для разговора рядом с Claude: через вход Google, совместимый с OpenAI;
скриншоты ему не уходят (просьбы про экран — сильному мозгу), запасным сам не становится."""
import unittest
from unittest import mock

from chloe import config
from chloe.thinking import openai_chat as oc
from chloe.thinking import router


class Mixed(unittest.TestCase):
    def setUp(self):
        for name, value in {"PROVIDER": "qwen", "MODEL_FAST": "gemini-3.5-flash", "MODEL_STRONG": "claude-sonnet-5-5",
                            "MODEL_EYES": None, "QWEN_KEY": "q", "DEEPSEEK_KEY": "", "ANTHROPIC_KEY": "a",
                            "GEMINI_KEY": "g"}.items():
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        oc.cooldown.clear()

    def test_gemini_first_then_backups(self):
        chain = oc.backups("gemini-3.5-flash")
        self.assertEqual(chain[0], "gemini-3.5-flash")
        self.assertIn("qwen3.8-flash", chain)                     # Qwen — запасной, если Gemini упёрся в лимит
        self.assertIn("claude-haiku-5-5", chain)
        self.assertEqual(oc.provider_of("gemini-3.5-flash"), "gemini")

    def test_never_a_backup_unless_chosen(self):
        with mock.patch.object(config, "MODEL_FAST", "claude-haiku-5-5"):
            self.assertFalse(any(m.startswith("gemini") for m in oc.backups("claude-haiku-5-5")))
            self.assertFalse(any(m.startswith("gemini") for m in oc.backups("claude-sonnet-5-5")))

    def test_rate_limit_moves_on(self):
        oc.cooldown["gemini-3.5-flash"] = 10 ** 12                  # 429 бесплатного лимита — пауза
        self.assertNotIn("gemini-3.5-flash", oc.backups("gemini-3.5-flash"))

    def test_no_thinking_for_voice(self):
        self.assertEqual(oc.request_args("gemini-3.5-flash"), ("gemini-3.5-flash", {"reasoning_effort": "none"}))

    def test_screenshots_never_sent(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "что на экране?"},
                                             {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA"}}]}]
        out = oc.for_provider(msgs, "gemini")
        self.assertIsInstance(out[0]["content"], str)
        self.assertNotIn("base64", out[0]["content"])

    def test_screen_request_goes_to_strong(self):
        self.assertFalse(router.sees_images("gemini-3.5-flash"))
        from chloe.vision import vision

        with mock.patch.object(type(vision), "enabled", new_callable=mock.PropertyMock, return_value=True):
            r = router.Route("что это за ошибка на экране?")
        self.assertEqual(r.model, "claude-sonnet-5-5")

    def test_simple_talk_goes_to_gemini(self):
        self.assertEqual(router.Route("привет, как дела?").model, "gemini-3.5-flash")

    def test_gemini_alone_still_sees(self):
        with mock.patch.object(config, "PROVIDER", "gemini"):
            self.assertTrue(router.sees_images("gemini-3.5-flash"))

    def test_client_points_at_google(self):
        clients = oc.make_clients()
        self.assertIn("generativelanguage.googleapis.com/v1beta/openai", str(clients["gemini"].base_url))


if __name__ == "__main__":
    unittest.main()
