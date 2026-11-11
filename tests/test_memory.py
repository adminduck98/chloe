"""Память: у каждой записи видна дата — изменчивое мозг проверяет, а не повторяет по памяти."""
import unittest

from chloe import memory as M


class MemoryDates(unittest.TestCase):
    def test_prompt_shows_when_written(self):
        self.assertEqual(M.when({"time": "2026-11-09 17:30"}), " (записано 09.11)")
        self.assertEqual(M.when({}), "")

    def test_system_prompt_tells_to_check_old_changing_facts(self):
        from chloe.thinking.prompt import system_prompt

        text = system_prompt()
        self.assertIn("Память верна на дату записи", text)
        self.assertIn("проверь инструментом", text)


if __name__ == "__main__":
    unittest.main()
