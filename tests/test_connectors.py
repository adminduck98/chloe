"""Connector Layer: реестр подключений, выключение (инструменты закрыты), забыть, основа не выключается."""
import unittest
from unittest import mock

from chloe import connectors as cn
from chloe.journal import journal
from chloe.permissions import permissions
from chloe.settings import settings
from chloe.tools import HANDLERS, run_tool
from chloe.tools import conn


class Registry(unittest.TestCase):
    def setUp(self):
        settings.set("connectors_off", None)
        self.addCleanup(settings.set, "connectors_off", None)

    def test_every_tool_belongs_to_a_real_tool(self):
        for c in cn.REGISTRY:
            for t in c.tools:
                self.assertIn(t, HANDLERS, "{}: {}".format(c.id, t))

    def test_find_by_name_and_alias(self):
        self.assertEqual(cn.find("телеграм").id, "telegram")
        self.assertEqual(cn.find("календарь").id, "google_calendar")
        self.assertEqual(cn.find("Bailian").id, "bailian_cli")
        self.assertIsNone(cn.find("микроволновка"))

    def test_off_blocks_only_its_tools(self):
        self.assertTrue(cn.set_on("telegram", False))
        verdict = permissions.check("tg_send", {"chat": "мама", "text": "привет"})
        self.assertEqual(verdict[0], "block")
        self.assertIn("Telegram", verdict[1])
        self.assertIsNone(permissions.check("calendar", {"action": "list"}))
        out, _, failed = run_tool("tg_read", {"chat": "мама"})
        self.assertIn("выключено", out)
        self.assertTrue(cn.set_on("telegram", True))
        self.assertIsNone(cn.blocks("tg_send"))

    def test_core_and_planned_cannot_be_switched(self):
        self.assertFalse(cn.set_on("qwen", False))
        self.assertFalse(cn.set_on("glasses", True))
        self.assertIn("основа", conn.tool_connectors({"action": "off", "name": "мозг claude"}))

    def test_broken_status_does_not_break_list(self):
        bad = cn.Connector("x", "Сломанное", "тест", status=lambda: 1 / 0)
        with mock.patch.object(cn, "REGISTRY", cn.REGISTRY + [bad]):
            row = next(r for r in cn.overview() if r["id"] == "x")
        self.assertEqual(row["level"], "fail")

    def test_usage_counts_from_journal(self):
        before = cn.usage()["google_calendar"]["count"]
        journal.add("tool", "Календарь", "calendar: list", {"tool": "calendar", "args": {}, "result": "ok"})
        u = cn.usage()["google_calendar"]
        self.assertEqual(u["count"], before + 1)
        self.assertIsNotNone(u["last"])


class Tool(unittest.TestCase):
    def setUp(self):
        settings.set("connectors_off", None)
        self.addCleanup(settings.set, "connectors_off", None)

    def test_list_off_on(self):
        out = conn.tool_connectors({"action": "list"})
        self.assertIn("Google Calendar", out)
        self.assertIn("Home Assistant", out)
        self.assertIn("Выключила", conn.tool_connectors({"action": "off", "name": "интернет"}))
        self.assertIsNotNone(cn.blocks("web_search"))
        with mock.patch.object(conn, "confirm", return_value=False):
            self.assertIn("Оставила", conn.tool_connectors({"action": "on", "name": "интернет"}))
        with mock.patch.object(conn, "confirm", return_value=True):
            self.assertIn("Включила", conn.tool_connectors({"action": "on", "name": "интернет"}))
        self.assertIsNone(cn.blocks("web_search"))

    def test_forget_needs_yes(self):
        fake = mock.Mock(return_value="вход стёрт")
        c = cn.BY_ID["google_calendar"]
        with mock.patch.object(c, "_forget", fake):
            with mock.patch.object(conn, "confirm", return_value=False):
                self.assertEqual(conn.tool_connectors({"action": "forget", "name": "календарь"}), "Не стала.")
            fake.assert_not_called()
            with mock.patch.object(conn, "confirm", return_value=True):
                self.assertIn("вход стёрт", conn.tool_connectors({"action": "forget", "name": "календарь"}))
        self.assertIn("нечего забывать", conn.tool_connectors({"action": "forget", "name": "интернет"}))

    def test_window_api(self):
        from chloe.app import Api

        rows = Api().connectors_get(False)
        self.assertTrue(any(r["id"] == "telegram" for r in rows))
        self.assertTrue(Api().connector_set("phone", False))
        self.assertFalse(cn.is_on("phone"))


if __name__ == "__main__":
    unittest.main()
