"""DeepSeek Flash видит экран (V4 Pro — нет); со скриншотом первыми идут те, кто его увидит; Qwen можно убрать
из разговора (CHLOE_BRAIN_SKIP) — он остаётся для картинок и видео."""
import unittest
from unittest import mock

from chloe import config
from chloe.thinking import openai_chat as oc
from chloe.thinking import router

SHOT = [{"role": "user", "content": [{"type": "text", "text": "что на экране?"},
                                     {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA"}}]}]


class Eyes(unittest.TestCase):
    def test_flash_sees_pro_does_not(self):
        self.assertTrue(oc.sees("deepseek-flash"))
        self.assertFalse(oc.sees("deepseek-v4-pro"))
        self.assertTrue(router.sees_images("deepseek-flash"))
        self.assertFalse(router.sees_images("deepseek-v4-pro"))

    def test_history_keeps_image_only_for_flash(self):
        self.assertIsInstance(oc.for_provider(SHOT, "deepseek", "deepseek-flash")[0]["content"], list)
        self.assertIn("не видит", oc.for_provider(SHOT, "deepseek", "deepseek-v4-pro")[0]["content"])

    def test_screenshot_goes_to_seeing_models_first(self):
        tried = []

        class Fake:
            class chat:
                class completions:
                    @staticmethod
                    def create(model, messages, **kw):
                        tried.append((model, isinstance(messages[-1]["content"], list)))
                        msg = mock.Mock(content="Браузер.", tool_calls=None)
                        return mock.Mock(choices=[mock.Mock(message=msg)], usage=None)
        with mock.patch.object(oc, "backups", return_value=["deepseek-v4-pro", "deepseek-flash"]):
            _, model = oc.chat({"deepseek": Fake}, SHOT, "deepseek-v4-pro", tools=False)
        self.assertEqual(model, "deepseek-flash")
        self.assertEqual(tried, [("deepseek-flash", True)])


class NoLoop(unittest.TestCase):
    def test_fast_brain_that_sees_takes_screenshot_itself(self):
        with mock.patch.object(config, "MODEL_FAST", "deepseek-flash"), mock.patch.object(config, "MODEL_STRONG", "deepseek-v4-pro"), \
                mock.patch.object(config, "MODEL_EYES", "deepseek-flash", create=True):
            r = router.Route("привет")
            self.assertFalse(r.redo_for(["screenshot"]))                     # раньше: переключение на себя же — по кругу
            self.assertEqual(r.model, "deepseek-flash")


class Skip(unittest.TestCase):
    def test_qwen_not_a_brain_backup(self):
        with mock.patch.object(oc, "BRAIN_SKIP", {"qwen"}), mock.patch.object(config, "PROVIDER", "deepseek"), \
                mock.patch.object(config, "MODEL_FAST", "deepseek-flash"), mock.patch.object(config, "MODEL_STRONG", "deepseek-v4-pro"), \
                mock.patch.object(config, "MODEL_EYES", None), mock.patch.object(config, "has_key", return_value=True):
            chain = oc.backups("deepseek-flash")
        self.assertFalse([m for m in chain if m.startswith("qwen")])
        self.assertIn("claude-haiku-5-5", chain)
        self.assertNotIn("claude-sonnet-5-5", chain)                       # дороже выбранных — не зовётся


if __name__ == "__main__":
    unittest.main()
