"""System State: самопроверка Chloe. Сеть и внешние сервисы подменены."""
import json
import time
import unittest
from unittest import mock

from chloe import system_state as ss
from chloe.journal import journal
from chloe.tools import HANDLERS
from chloe.tools import selfcheck as tool


class Quick(unittest.TestCase):
    def test_fast_and_complete(self):
        t = time.time()
        items = ss.quick()
        self.assertLess(time.time() - t, 3)
        areas = {x["area"] for x in items}
        for area in ("Мозг", "Голос", "Слух", "Сервисы", "Система", "Ошибки", "Права"):
            self.assertIn(area, areas)
        self.assertTrue(all(x["level"] in ss.LEVELS for x in items))

    def test_no_key_values_in_output(self):
        with mock.patch.object(ss.config, "QWEN_KEY", "sk-sp-SECRETVALUE123"), mock.patch.object(ss.config, "PROVIDER", "qwen"):
            text = ss.report(ss.quick())
        self.assertNotIn("SECRETVALUE", text)

    def test_broken_check_does_not_break_all(self):
        with mock.patch.object(ss, "FAST", (("Мозг", "Мозг", lambda: 1 / 0), ("Права", "Права", ss.rights))):
            items = ss.quick()
        self.assertEqual(items[0]["level"], "fail")
        self.assertIn("ZeroDivisionError", items[0]["detail"])
        self.assertEqual(items[1]["area"], "Права")


class Errors(unittest.TestCase):
    def log(self, result, ok=False):
        journal.add("tool", "Поиск в интернете", "web_search", json.dumps({"tool": "web_search", "result": result}, ensure_ascii=False), ok=ok)

    def test_refusals_are_not_errors(self):
        before = ss.errors()
        self.log("Пользователь отклонил команду.")
        self.log("Отказано: это приватная папка (Private Vault)")
        self.assertEqual(ss.errors()["detail"], before["detail"])
        self.log("Ошибка: error sending request")
        after = ss.errors()
        self.assertEqual(after["level"], "warn")
        self.assertIn("Поиск в интернете", after["detail"])
        self.assertIn("error sending", after["last"])


class Verdict(unittest.TestCase):
    def test_levels(self):
        ok = ss.item("A", "a", "ok", "")
        self.assertEqual(ss.verdict([ok, ss.item("A", "b", "off", "")])[0], "ok")
        self.assertEqual(ss.verdict([ok, ss.item("A", "b", "warn", "мало места")])[0], "warn")
        level, text = ss.verdict([ss.item("Мозг", "Claude", "fail", "нет денег"), ss.item("A", "b", "warn", "")])
        self.assertEqual(level, "fail")
        self.assertIn("Claude — нет денег", text)


class Deep(unittest.TestCase):
    def test_deep_replaces_quick_items_by_name(self):
        fake = (("Сервисы", "Google Calendar", lambda: ss.item("Сервисы", "Google Calendar", "fail", "Google отозвал доступ")),
                ("Мозг", "Мозг", lambda: [ss.item("Мозг", "Claude", "ok", "ответил")]))
        with mock.patch.object(ss, "DEEP", fake):
            items = ss.deep()
        cal = [x for x in items if x["name"] == "Google Calendar"]
        self.assertEqual(len(cal), 1)
        self.assertEqual(cal[0]["level"], "fail")
        self.assertTrue(any(x["name"] == "Claude" for x in items))
        self.assertEqual(items[0]["area"], "Мозг")

    def test_brain_ping_reports_reason(self):
        err = Exception("x")
        err.status_code = 402
        with mock.patch.object(ss.config, "QWEN_KEY", None), mock.patch.object(ss.config, "DEEPSEEK_KEY", "k"), \
                mock.patch.object(ss.config, "ANTHROPIC_KEY", None), \
                mock.patch("openai.OpenAI", side_effect=err):
            out = ss.ping_brains()
        self.assertEqual(out[0]["level"], "fail")
        self.assertIn("нет денег", out[0]["detail"])


class Tool(unittest.TestCase):
    def test_registered_and_saves(self):
        self.assertIn("system_state", HANDLERS)
        out = tool.tool_system_state({})
        self.assertIn("Мозг:", out)
        saved = json.loads(ss.snapshot_file().read_text(encoding="utf-8"))
        self.assertTrue(saved["items"])

    def test_window_api(self):
        from chloe.app import Api

        r = Api().system_health(False)
        self.assertIn(r["level"], ("ok", "warn", "fail"))
        self.assertFalse(r["deep"])



class LastErrorTime(unittest.TestCase):
    def test_error_item_says_when_it_last_happened(self):
        journal.add("tool", "Поиск в интернете", "web_search: x", json.dumps({"tool": "web_search", "result": "Ошибка: error sending request"}, ensure_ascii=False), ok=False)
        item = ss.errors()
        self.assertRegex(item["detail"], r"до \d\d:\d\d")                    # чтобы старые ошибки не выдавались за текущую поломку
        self.assertRegex(item["last"], r"последняя в \d\d:\d\d")


if __name__ == "__main__":
    unittest.main()
