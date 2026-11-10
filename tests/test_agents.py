"""Multi-Agent: роли со своими инструментами, цикл агента, чужой инструмент — отказ, фоновый запуск и отчёт."""
import json
import threading
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from chloe import agents as ag
from chloe.tools import HANDLERS
from chloe.tools import team


def call(name, args, cid="c1"):
    return NS(id=cid, function=NS(name=name, arguments=json.dumps(args)))


def scripted(*replies):
    """Поддельная модель: по очереди отдаёт ответы; запоминает, какие инструменты ей дали."""
    seen = {"tools": []}
    replies = list(replies)

    def chat(clients, messages, model, tools=True, max_tokens=1500):
        seen["tools"].append(tools)
        r = replies.pop(0)
        return (NS(content=r, tool_calls=None) if isinstance(r, str) else NS(content="", tool_calls=r)), model
    return chat, seen


class Roles(unittest.TestCase):
    def test_tools_exist_and_are_safe(self):
        writes = {"run_command", "write_text_file", "delete_path", "move_path", "tg_send", "social", "permissions", "safe_mode",
                  "delegate", "workflows_add", "power", "subscriptions"}
        for k, a in ag.AGENTS.items():
            self.assertTrue(a["tools"] <= set(HANDLERS), k)
            self.assertFalse(a["tools"] & writes, k)                 # агенты не пишут и не отправляют
            self.assertNotIn("delegate", a["tools"])                  # и не поручают друг другу

    def test_find(self):
        self.assertEqual(ag.find("исследователь"), "researcher")
        self.assertEqual(ag.find("security"), "security")
        self.assertIsNone(ag.find("повар"))


class Loop(unittest.TestCase):
    def test_runs_tools_through_runner_and_reports(self):
        chat, seen = scripted([call("web_search", {"query": "курс"})], "Итог: 11 994 сума (cbu.uz).")
        ran = []
        status, report, steps, used = ag.run_agent("researcher", "узнай курс", chat=chat, clients={},
                                                   tool_runner=lambda n, a: (ran.append((n, a)) or "результат", False, False))
        self.assertEqual((status, steps, used), ("готово", 1, {"web_search"}))
        self.assertIn("11 994", report)
        self.assertEqual(ran, [("web_search", {"query": "курс"})])
        self.assertEqual(seen["tools"][0], ag.AGENTS["researcher"]["tools"])    # модели дали только инструменты роли

    def test_foreign_tool_refused(self):
        chat, _ = scripted([call("delete_path", {"path": "~/x"})], "Не смогла удалить.")
        ran = []
        status, report, steps, used = ag.run_agent("researcher", "удали файл", chat=chat, clients={},
                                                   tool_runner=lambda n, a: (ran.append(n) or "ok", False, False))
        self.assertEqual(ran, [])
        self.assertEqual(used, set())

    def test_step_limit_then_summary(self):
        many = [[call("web_search", {"query": str(i)}, "c%d" % i)] for i in range(ag.AGENTS["projects"]["steps"])]
        chat, seen = scripted(*many, "Сводка по тому, что успел.")
        status, report, steps, _ = ag.run_agent("projects", "много шагов", chat=chat, clients={},
                                                tool_runner=lambda n, a: ("ok", False, False))
        self.assertEqual(steps, ag.AGENTS["projects"]["steps"])
        self.assertEqual(report, "Сводка по тому, что успел.")
        self.assertIs(seen["tools"][-1], False)                          # итог — без инструментов


class Delegate(unittest.TestCase):
    def setUp(self):
        self.runs = ag.Runs(":memory:")
        p = mock.patch.object(ag, "runs", self.runs)
        p.start()
        self.addCleanup(p.stop)

    def test_background_run_announces_and_stores(self):
        done = threading.Event()
        said = []
        chat, _ = scripted("Отчёт готов: всё в порядке.")
        rid = ag.delegate("security", "проверь защиту", announce=lambda r, s, t: (said.append((r, s, t)), done.set()),
                          chat=chat, clients={})
        self.assertTrue(done.wait(5))
        r = self.runs.get(rid)
        self.assertEqual((r["status"], r["report"]), ("готово", "Отчёт готов: всё в порядке."))
        self.assertEqual(said[0][0], rid)

    def test_parallel_limit_and_errors(self):
        for _ in range(ag.MAX_PARALLEL):
            self.runs.start("researcher", "занято")
        with self.assertRaises(ag.AgentError):
            ag.delegate("researcher", "ещё одна")
        rid = ag.delegate("developer", "сломайся", wait=True, chat=lambda *a, **k: 1 / 0, clients={})
        self.assertEqual(self.runs.get(rid)["status"], "ошибка")

    def test_tools(self):
        self.assertIn("delegate", HANDLERS)
        self.assertIn("Нет такого агента", team.tool_delegate({"agent": "повар", "task": "сварить суп"}))
        self.assertIn("Исследователь", team.tool_agents({"action": "list"}))
        rid = self.runs.start("researcher", "тест")
        self.runs.finish(rid, "готово", "Отчёт.", 2, {"web_search"})
        self.assertIn("Отчёт.", team.tool_agents({"action": "show", "id": rid}))
        self.assertIn("№{}".format(rid), team.tool_agents({"action": "reports"}))
        with mock.patch.object(ag, "delegate", return_value=7) as d:
            self.assertIn("№7", team.tool_delegate({"agent": "researcher", "task": "изучи вопрос"}))
        self.assertEqual(d.call_args[0][:2], ("researcher", "изучи вопрос"))


if __name__ == "__main__":
    unittest.main()
