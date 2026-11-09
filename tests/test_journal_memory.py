"""Журнал и память: запись, поиск, группировка по просьбе, удаление; добавить, исправить, забыть."""
import json
import unittest
from unittest import mock

from chloe.app import Api
from chloe.journal import journal
from chloe.memory import Memory, memory
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False
api = Api()


class JournalTest(unittest.TestCase):
    def setUp(self):
        journal.clear()

    def test_request_groups_its_steps(self):
        first = journal.add("heard", "Голос", "сколько файлов в загрузках")
        run_tool("list_folder", {"path": "~"})
        voice.say("Готово")
        journal.add("heard", "Голос", "вторая просьба")   # новая просьба не становится шагом прошлой
        steps = api.journal_get(first)["steps"]
        self.assertEqual([s["kind"] for s in steps], ["tool", "said"])

    def test_search_and_skill_filter(self):
        journal.add("heard", "Голос", "найди файл")
        run_tool("read_text_file", {"path": "~/нет-такого.txt"})
        self.assertEqual(len(api.journal_list(query="нет-такого")), 1)
        self.assertTrue(all(e["skill"] == "Файлы" for e in api.journal_list(skill="Файлы")))
        self.assertFalse(api.journal_list(skill="Файлы")[0]["ok"])   # ошибка видна в журнале

    def test_screenshot_saved_and_deleted_with_request(self):
        h = journal.add("heard", "Голос", "что на экране")
        shot = journal.add("tool", "Экран", "screenshot", screen_png=b"\x89PNG fake")
        self.assertTrue(api.journal_get(shot)["screen"].startswith("data:image/png;base64,"))
        api.journal_delete(h)
        self.assertEqual(api.journal_list(), [])
        self.assertEqual(list(journal.screens.glob("*.png")), [])


class MemoryTest(unittest.TestCase):
    def setUp(self):
        for m in list(memory.items):
            memory.delete(m["id"])

    def test_add_edit_delete(self):
        item = api.memory_add("Я люблю чёрный кофе")
        self.assertTrue(api.memory_edit(item["id"], "Я люблю зелёный чай"))
        self.assertEqual(memory.get(item["id"])["text"], "Я люблю зелёный чай")
        self.assertIn("[{}] Я люблю зелёный чай".format(item["id"]), memory.prompt())
        self.assertTrue(api.memory_delete(item["id"]))
        self.assertEqual(memory.items, [])

    def test_forget_by_voice_needs_yes(self):
        item = memory.add("старый факт", "Память")
        with mock.patch("builtins.input", return_value="нет"):
            run_tool("forget", {"id": item["id"]})
        self.assertIsNotNone(memory.get(item["id"]))
        with mock.patch("builtins.input", return_value="да, делай"):
            run_tool("forget", {"id": item["id"]})
        self.assertIsNone(memory.get(item["id"]))

    def test_old_file_without_ids_gets_numbered(self):
        path = memory.path.with_name("old-memory.json")
        path.write_text(json.dumps([{"text": "a", "zone": "Память"}, {"text": "b", "zone": "Память"}]))
        self.assertEqual([m["id"] for m in Memory(path).items], [1, 2])


if __name__ == "__main__":
    unittest.main()
