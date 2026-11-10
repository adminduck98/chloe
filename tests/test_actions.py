"""Action Center и безопасный режим."""
import threading
import time
import unittest
from unittest import mock

from chloe import actions, safemode
from chloe.journal import journal
from chloe.permissions import permissions
from chloe.settings import settings
from chloe.tools import HANDLERS, run_tool
from chloe.tools import center


class SafeMode(unittest.TestCase):
    def setUp(self):
        settings.set("safe_mode", False)
        self.addCleanup(settings.set, "safe_mode", False)
        old_vision = settings.get("vision")
        settings.set("vision", False)                 # иначе выключение режима запустило бы настоящее зрение в тестах
        self.addCleanup(settings.set, "vision", old_vision)

    def test_blocks_actions_but_not_self_check(self):
        safemode.enable("тест")
        for tool, args in (("run_command", {"command": "ls"}), ("tg_send", {"chat": "x", "text": "y"}), ("read_text_file", {"path": "~/a"}),
                           ("web_search", {"query": "x"}), ("social", {"action": "list"}), ("phone", {"action": "status"})):
            verdict = permissions.check(tool, args)
            self.assertEqual(verdict[0], "block", tool)
            self.assertIn("безопасный режим", verdict[1])
        for tool in ("system_state", "security", "actions", "safe_mode", "list_reminders"):
            self.assertIsNone(permissions.check(tool, {}), tool)
        out, _, failed = run_tool("run_command", {"command": "echo hi"})
        self.assertIn("безопасный режим", out)
        self.assertTrue(failed)

    def test_enable_saves_state_and_vision(self):
        from chloe.vision import vision

        settings.set("vision", True)
        with mock.patch.object(type(permissions), "screen_allowed", return_value=True), mock.patch.object(vision, "start"):
            self.assertTrue(vision.enabled)
            done = safemode.enable("тест")
            self.assertFalse(vision.enabled)
            self.assertIn("зрение выключено", done)
            self.assertTrue(any("копия" in d for d in done))
            back = safemode.disable()
            self.assertTrue(vision.enabled)
        self.assertIn("зрение снова включено", back)
        self.assertTrue(settings.get("vision"))                       # настройка пользователя не тронута
        self.assertFalse(safemode.on())

    def test_automations_paused(self):
        from chloe.tools import news as tn
        from chloe.tools import social as ts

        settings.set("morning_brief", True)
        settings.set("brief_day", None)
        safemode.enable("тест")
        morning = time.mktime(time.strptime("2026-11-11 08:00", "%Y-%m-%d %H:%M"))
        self.assertFalse(tn.morning_due(morning))
        with mock.patch.object(ts.social, "due_now") as due:
            stop = threading.Event()
            t = threading.Thread(target=ts.watcher, args=(lambda x: None, 0.01, stop))
            t.start()
            time.sleep(0.05)
            stop.set()
            t.join(2)
        due.assert_not_called()
        settings.set("morning_brief", None)

    def test_tool_off_needs_yes(self):
        self.assertIn("Безопасный режим", center.tool_safe_mode({"action": "on"}))
        with mock.patch.object(center, "confirm", return_value=False):
            self.assertEqual(center.tool_safe_mode({"action": "off"}), "Оставила безопасный режим.")
        self.assertTrue(safemode.on())
        with mock.patch.object(center, "confirm", return_value=True):
            self.assertIn("Выключила", center.tool_safe_mode({"action": "off"}))
        self.assertFalse(safemode.on())

    def test_in_self_check(self):
        from chloe import system_state

        safemode.enable("тест")
        self.assertTrue(any(x["name"] == "Безопасный режим" for x in system_state.quick()))


class Center(unittest.TestCase):
    def test_today_counts_errors_and_refusals(self):
        journal.add("tool", "Поиск", "web_search: x", {"tool": "web_search", "result": "Ошибка: error sending request for url (https://www.mojeek.com/search?q=%D0%A4)"}, ok=False)
        journal.add("tool", "Команды", "run_command: y", {"tool": "run_command", "result": "Пользователь отклонил команду."}, ok=False)
        journal.add("confirm", "Подтверждение", "Выполнить? — нет", {"yes": False}, ok=False)
        o = actions.overview()
        mine = [s for s in o["today"] if s["title"] in ("web_search: x", "run_command: y", "Выполнить? — нет")]
        err = {s["title"]: s["error"] for s in mine}
        self.assertEqual(err, {"web_search: x": True, "run_command: y": False, "Выполнить? — нет": False})
        web = next(s for s in mine if s["title"] == "web_search: x")
        self.assertIn("www.mojeek.com", web["result"])
        self.assertNotIn("%D0", web["result"])

    def test_pending_question_visible_and_answerable(self):
        from chloe.voice import voice

        with mock.patch.object(voice, "pending", {"question": "Удалить файл?", "since": time.time()}):
            w = actions.waiting()
        self.assertEqual(w[0]["kind"], "question")
        from chloe.app import Api
        from chloe.signals import commands

        Api().answer_pending(True)
        self.assertEqual(str(commands.get_nowait()), "да")

    def test_tools_registered(self):
        for t in ("actions", "safe_mode"):
            self.assertIn(t, HANDLERS)
        self.assertIn("Сегодня:", center.tool_actions({}))
        self.assertIn("Ошибки", center.tool_actions({"view": "errors"}) + "Ошибки")


if __name__ == "__main__":
    unittest.main()
