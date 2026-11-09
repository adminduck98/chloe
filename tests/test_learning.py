"""Обучение словами: свой навык из прошлой задачи, сценарий по слову, уроки. Во временной домашней папке."""
import shutil
import unittest

from chloe import learning, skillbook
from chloe.journal import journal
from chloe.settings import settings
from chloe.thinking.prompt import system_prompt
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False


class Learning(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(skillbook.USER_DIR, ignore_errors=True)
        settings.set("lessons", [])

    def test_remember_how_it_was_done(self):
        journal.add("heard", "Голос", "включи на ютубе лофи")
        journal.add("tool", "Браузер", "open_url: https://youtube.com/results?search_query=lofi", {"tool": "open_url"})
        journal.add("tool", "Экран", "mouse_click: 400, 300", {"tool": "mouse_click"}, ok=False)
        journal.add("tool", "Экран", "press_keys: k", {"tool": "press_keys"})
        journal.add("heard", "Голос", "запомни, как это делается")
        out, _, failed = run_tool("save_skill", {"name": "Лофи на ютубе", "when": "когда просят включить лофи",
                                                 "steps": "1. open_url поиска lofi 2. press_keys k"})
        self.assertFalse(failed, out)
        s = skillbook.get("лофи-на-ютубе")
        self.assertIsNotNone(s)
        self.assertEqual(s["description"], "когда просят включить лофи")
        self.assertIn("Просьба: «включи на ютубе лофи»", s["body"])
        self.assertIn("open_url: https://youtube.com/results?search_query=lofi", s["body"])
        self.assertIn("(не сработало)", s["body"])            # неудачный клик помечен
        self.assertIn("лофи-на-ютубе", system_prompt())      # виден в списке навыков
        self.assertIn("лофи-на-ютубе", run_tool("learned_list", {})[0])

    def test_scenario_starts_by_its_word(self):
        run_tool("save_skill", {"name": "работаем", "when": "режим работы", "triggers": ["работаем", "за работу"],
                                "steps": "открой проект chloe, закрой ютуб", "from_last_task": False})
        for said in ("Работаем!", "работаем", "за работу", "Хлоя за работу"[5:]):
            self.assertEqual(learning.match_trigger(said)["name"], "работаем", said)
        for said in ("мы сегодня работаем до вечера", "работа", ""):
            self.assertIsNone(learning.match_trigger(said), said)
        self.assertIn("за работу", run_tool("learned_list", {})[0])

    def test_same_name_updates(self):
        run_tool("save_skill", {"name": "музыка", "when": "старое", "steps": "старые шаги", "from_last_task": False})
        run_tool("save_skill", {"name": "музыка", "when": "новое", "steps": "новые шаги", "from_last_task": False})
        s = skillbook.get("музыка")
        self.assertEqual(s["description"], "новое")
        self.assertNotIn("старые шаги", s["body"])

    def test_lessons(self):
        run_tool("learn_lesson", {"text": "YouTube открывай в Firefox, а не в Chrome"})
        run_tool("learn_lesson", {"text": "YouTube открывай в Firefox, а не в Chrome"})   # повтор не дублируется
        run_tool("learn_lesson", {"text": "Отвечай короче"})
        prompt = system_prompt()
        self.assertIn("Правила, которым тебя научил пользователь", prompt)
        self.assertIn("1. YouTube открывай в Firefox", prompt)
        self.assertIn("2. Отвечай короче", prompt)
        out = run_tool("forget_lesson", {"number": 1})[0]
        self.assertIn("Firefox", out)
        self.assertNotIn("Firefox", system_prompt())
        self.assertTrue(run_tool("forget_lesson", {"number": 9})[2])   # нет такого — честно

    def test_teaching_goes_to_strong_brain(self):
        from unittest import mock

        from chloe import config
        from chloe.thinking.router import Route

        with mock.patch.object(config, "MODEL_FAST", "fast"), mock.patch.object(config, "MODEL_STRONG", "strong"):
            for text in ("Когда я говорю «работаем» — открой проект", "Неправильно, ютуб открывай в фаерфоксе",
                         "запомни, как это делается", "впредь отвечай короче"):
                self.assertEqual(Route(text).model, "strong", text)
            for text in ("какая погода", "запомни, что я живу в Ташкенте"):
                self.assertEqual(Route(text).model, "fast", text)


if __name__ == "__main__":
    unittest.main()
