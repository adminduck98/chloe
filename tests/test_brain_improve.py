"""Улучшения мозга: не повторять неудачный шаг по кругу, смотреть на экран моделью с глазами,
память без дублей и с давними воспоминаниями по словам просьбы, кадр экрана — только когда просьба про экран."""
import unittest
from unittest import mock

from chloe import config
from chloe.memory import memory
from chloe.settings import settings
from chloe.signals import state
from chloe.thinking import router
from chloe.thinking.prompt import start_thinking
from chloe.tools import HANDLERS, run_tool
from chloe.vision import vision, wants_frame


class RepeatGuard(unittest.TestCase):
    def setUp(self):
        state["task_failed"] = {}

    def test_same_failed_step_is_not_repeated_forever(self):
        calls = []

        def broken(a):
            calls.append(a)
            raise RuntimeError("нет такого окна")

        with mock.patch.dict(HANDLERS, {"window": broken}):
            for _ in range(2):
                out, is_error, failed = run_tool("window", {"action": "focus", "name": "Фотошоп"})
                self.assertTrue(failed)
            out, is_error, failed = run_tool("window", {"action": "focus", "name": "Фотошоп"})
            self.assertTrue(failed)
            self.assertIn("уже дважды не сработал", out)
            self.assertEqual(len(calls), 2)                 # третий раз даже не запускался
            run_tool("window", {"action": "focus", "name": "Photoshop"})   # другие параметры — можно
            self.assertEqual(len(calls), 3)

    def test_new_request_starts_clean(self):
        state["task_failed"] = {"window:{}": 5}
        with mock.patch("chloe.thinking.think_claude", return_value="ок"), \
             mock.patch.object(config, "PROVIDER", "anthropic"):
            from chloe.thinking import think

            think(None, [], "привет")
        self.assertEqual(state["task_failed"], {})


class LookWithEyes(unittest.TestCase):
    def test_screen_question_goes_to_model_that_sees(self):
        settings.set("vision", True)
        with mock.patch.object(config, "MODEL_FAST", "deepseek-flash"), \
             mock.patch.object(config, "MODEL_STRONG", "deepseek-v4-pro"), \
             mock.patch.object(config, "MODEL_EYES", "claude-haiku-5-5", create=True):
            self.assertEqual(router.Route("что это за ошибка?").model, "claude-haiku-5-5")
            self.assertEqual(router.Route("поставь будильник на 7").model, "deepseek-flash")
        with mock.patch.object(config, "MODEL_FAST", "qwen3.8-flash"), \
             mock.patch.object(config, "MODEL_STRONG", "qwen3.8-flash+thinking"), \
             mock.patch.object(config, "MODEL_EYES", None, create=True):
            self.assertEqual(router.Route("что это за ошибка?").model, "qwen3.8-flash")   # Qwen и так видит

    def test_sees_images(self):
        self.assertFalse(router.sees_images("deepseek-flash"))
        self.assertTrue(router.sees_images("qwen3.8-flash+thinking"))
        self.assertTrue(router.sees_images("claude-haiku-5-5"))
        self.assertTrue(router.sees_images("gemini-3.5-flash"))


class FramesOnlyWhenNeeded(unittest.TestCase):
    def tearDown(self):
        settings.set("vision_frames", "auto")

    def test_wants_frame(self):
        for t in ("что это за ошибка?", "переведи вот это", "что у меня на экране", "закрой это окно", "прочитай, что написано"):
            self.assertTrue(wants_frame(t), t)
        for t in ("поставь будильник на семь", "какая погода завтра", "сделай громче", "запомни, что я люблю чай"):
            self.assertFalse(wants_frame(t), t)
        settings.set("vision_frames", "always")
        self.assertTrue(wants_frame("какая погода завтра"))


class MemoryWithoutDuplicates(unittest.TestCase):
    def setUp(self):
        with memory.lock:
            memory.items = []
            memory._save()

    def test_same_fact_is_not_written_twice(self):
        out, _, _ = run_tool("remember", {"text": "Сестру зовут Мадина"})
        self.assertEqual(out, "Запомнила.")
        out, _, _ = run_tool("remember", {"text": "сестру зовут Мадина."})
        self.assertIn("уже помню", out)
        self.assertEqual(len(memory.items), 1)

    def test_new_version_replaces_old(self):
        run_tool("remember", {"text": "Музыку открывать в программе VLC плеер"})
        out, _, _ = run_tool("remember", {"text": "Музыку открывать в программе VLC плеере всегда"})
        self.assertIn("Обновила", out)
        self.assertEqual(len(memory.items), 1)
        self.assertEqual(memory.items[0]["text"], "Музыку открывать в программе VLC плеере всегда")

    def test_different_facts_stay_separate(self):
        run_tool("remember", {"text": "Сестру зовут Мадина"})
        run_tool("remember", {"text": "Магазин POINT TECH в Ташкенте"})
        self.assertEqual(len(memory.items), 2)

    def test_old_memory_is_recalled_by_words(self):
        memory.add("Сестру зовут Мадина, день рождения 12 марта", "Люди")
        for i in range(100):   # сотня фактов позже — старый выпал из подсказки
            memory.add("факт номер {} про работу".format(i), "Работа")
        self.assertNotIn("Мадина", memory.prompt())
        text = start_thinking("когда день рождения у сестры?")
        self.assertIn("Из давней памяти", text)
        self.assertIn("Мадина", text)
        self.assertNotIn("Из давней памяти", start_thinking("поставь будильник"))


class CoreStatus(unittest.TestCase):
    def test_system_status_for_the_core_panel(self):
        from chloe import remote
        from chloe.app import Api

        st = Api().system_status()
        for key in ("provider", "fast", "strong", "models", "vision", "memory", "skills", "reminders", "today", "busy"):
            self.assertIn(key, st)
        self.assertIn("calls", st["today"])
        self.assertIn("system_status", remote.ALLOWED)   # телефон-пульт тоже видит ядро


if __name__ == "__main__":
    unittest.main()
