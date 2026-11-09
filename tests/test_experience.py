"""Мозг — карта реального опыта: предметы из мира, связи шагов, вспоминание, повтор задачи. Всё во временной домашней папке."""
import types
import unittest
from unittest import mock

from chloe import config
from chloe.brain import brain
from chloe.config import HOME
from chloe.experience import recalled, things_of
from chloe.journal import journal
from chloe.memory import memory
from chloe.signals import interrupt
from chloe.thinking import think
from chloe.tools import run_tool
from chloe.tools.replay import past_task
from chloe.voice import voice

voice.enabled = False


def block(**kw):
    return types.SimpleNamespace(**kw)


class Calls:
    """Перехватывает вызовы мозга."""
    def __enter__(self):
        self.calls = []
        self.p = mock.patch.object(brain, "js", side_effect=lambda fn, *a: self.calls.append((fn,) + a))
        self.p.start()
        return self

    def __exit__(self, *a):
        self.p.stop()

    def of(self, fn):
        return [c[1:] for c in self.calls if c[0] == fn]


class Things(unittest.TestCase):
    def test_world_objects(self):
        self.assertEqual(things_of("open_app", {"name": "telegram"})[0]["name"], "Telegram")
        self.assertEqual(things_of("open_url", {"url": "https://www.youtube.com/watch?v=1"})[0]["name"], "youtube.com")
        names = [t["name"] for t in things_of("move_path", {"source": str(HOME / "Загрузки/a.pdf"),
                                                            "destination": str(HOME / "Документы/Отчёты")})]
        self.assertEqual(names, ["~/Загрузки", "~/Документы/Отчёты"])
        t = things_of("open_path", {"path": str(HOME / "Документы/план.txt")})
        self.assertEqual([x["kind"] for x in t], ["Папка", "Файл"])
        self.assertEqual(things_of("weather", {"city": "Ташкент, Узбекистан"})[0]["zone"], "Места")

    def test_failed_step_grows_nothing(self):
        self.assertEqual(things_of("open_app", {"name": "photoshop"}, ok=False), [])

    def test_steps_report_time_result_and_things(self):
        with Calls() as c:
            run_tool("list_folder", {"path": str(HOME)})
            run_tool("read_text_file", {"path": str(HOME / "нет-такого.txt")})
        steps = c.of("chloeStep")
        self.assertEqual(steps[0][0], "Файлы")
        self.assertTrue(steps[0][2])
        self.assertEqual(steps[0][3][0]["name"], "~")
        self.assertFalse(steps[1][2])          # ошибка → шрам
        self.assertEqual(steps[1][3], [])
        self.assertIsInstance(steps[0][1], float)


class Recall(unittest.TestCase):
    ITEMS = [{"text": "Любит чёрный кофе"}, {"text": "Отчёты хранит в папке Документы/Бухгалтерия"},
             {"text": "Сестру зовут Мадина"}]

    def test_memory_used_but_not_said(self):
        got = recalled("сохрани отчёт куда обычно", '{"path": "~/Документы/Бухгалтерия/отчёт.pdf"}', self.ITEMS)
        self.assertEqual(got, ["Отчёты хранит в папке Документы/Бухгалтерия"])

    def test_user_said_it_himself_is_not_recall(self):
        self.assertEqual(recalled("напиши Мадине привет", '{"chat": "Мадина"}', self.ITEMS), [])

    def test_unrelated_answer(self):
        self.assertEqual(recalled("который час", "Сейчас 15:40.", self.ITEMS), [])


class Scripted:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.messages = self

    def create(self, model, messages, **kw):
        kind, value, args = self.answers.pop(0)
        if kind == "tool":
            return block(stop_reason="tool_use", content=[block(type="tool_use", id="t%d" % len(self.answers), name=value, input=args)])
        return block(stop_reason="end_turn", content=[block(type="text", text=value)])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        config.PROVIDER = "anthropic"
        config.MODEL_FAST = config.MODEL_STRONG = "m"
        interrupt.clear()
        for m in list(memory.items):
            memory.delete(m["id"])
        memory.add("Сестру зовут Мадина", "Люди")

    def test_task_start_and_green_recall(self):
        fake = Scripted(("text", "Мадине сегодня можно позвонить после шести.", {}))
        with Calls() as c:
            think(fake, [], "когда лучше позвонить сестре")
        self.assertEqual(c.of("chloeTask"), [()])
        self.assertEqual(c.of("chloeRecall"), [("Сестру зовут Мадина",)])
        self.assertTrue(any(e["title"].startswith("Вспомнила") for e in journal.list(limit=5)))

    def test_replay_last_task(self):
        journal.add("heard", "Голос", "покажи домашнюю папку")
        run_tool("system_info", {})
        run_tool("list_folder", {"path": str(HOME)})
        journal.add("heard", "Голос", "покажи, как ты это сделала")   # текущая задача — не она
        title, steps = past_task(1)
        self.assertEqual(title, "покажи домашнюю папку")
        self.assertEqual([s["skill"] for s in steps], ["Система", "Файлы"])
        with Calls() as c:
            out, _, failed = run_tool("replay_task", {})
        self.assertFalse(failed, out)
        self.assertEqual(c.of("chloeReplay")[0][0], "покажи домашнюю папку")
        self.assertIn("Система → Файлы", out)


if __name__ == "__main__":
    unittest.main()
