"""Напоминания и таймеры: срок, озвучка, отмена, переживают перезапуск. Всё во временной домашней папке."""
import datetime
import time
import unittest
from unittest import mock

from chloe import reminders as rem
from chloe.config import JOURNAL_FILE
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False


class Reminders(unittest.TestCase):
    def setUp(self):
        for r in rem.reminders.pending():
            rem.reminders.cancel(r["id"])
        p = mock.patch.object(rem, "notify")
        self.notify = p.start()
        self.addCleanup(p.stop)

    def test_timer_rings_once(self):
        out, _, failed = run_tool("set_reminder", {"minutes": 5, "text": "выключить чайник"})
        self.assertFalse(failed, out)
        said = []
        self.assertEqual(rem.reminders.ring(said.append), 0)   # ещё рано
        self.assertEqual(rem.reminders.ring(said.append, now=time.time() + 301), 1)
        self.assertEqual(said, ["Напоминаю: выключить чайник"])
        self.notify.assert_called_once_with("выключить чайник")
        self.assertEqual(rem.reminders.ring(said.append, now=time.time() + 400), 0)   # второй раз не звонит

    def test_chloe_knows_she_already_reminded(self):
        """Напоминание прозвучало, потом «ты же не напомнила?» — модель видит, что напоминание было."""
        from chloe.signals import said_alone
        from chloe.thinking.prompt import start_thinking

        said_alone.clear()
        run_tool("set_reminder", {"minutes": 1, "text": "проверить подключение Claude"})
        rem.reminders.ring(lambda text: None, now=time.time() + 61)
        first = start_thinking("Ты же не напомнила")
        self.assertIn("Напоминаю: проверить подключение Claude", first)
        self.assertTrue(first.endswith("Ты же не напомнила"))
        self.assertNotIn("Напоминаю", start_thinking("Как дела"))   # сообщается один раз

    def test_clock_time_already_passed_means_tomorrow(self):
        now = datetime.datetime(2026, 11, 5, 20, 0).timestamp()
        due = datetime.datetime.fromtimestamp(rem.due_from(at="18:30", now=now))
        self.assertEqual((due.day, due.hour, due.minute), (6, 18, 30))
        due = datetime.datetime.fromtimestamp(rem.due_from(at="21:15", now=now))
        self.assertEqual((due.day, due.hour), (5, 21))

    def test_bad_time_is_honest(self):
        out, _, failed = run_tool("set_reminder", {"at": "после обеда", "text": "x"})
        self.assertTrue(failed)
        self.assertFalse(rem.reminders.pending())

    def test_list_and_cancel(self):
        run_tool("set_reminder", {"at": "2030-01-01 09:00", "text": "поздравить маму"})
        rid = rem.reminders.pending()[0]["id"]
        self.assertIn("поздравить маму", run_tool("list_reminders", {})[0])
        run_tool("cancel_reminder", {"id": rid})
        self.assertEqual(run_tool("list_reminders", {})[0], "Напоминаний нет.")

    def test_survives_restart_and_says_it_is_late(self):
        rem.reminders.add(time.time() - 3600, "позвонить Ахмеду")
        again = rem.Reminders(JOURNAL_FILE)   # как после перезапуска
        said = []
        again.ring(said.append)
        self.assertIn("позвонить Ахмеду (это было на", said[0])


if __name__ == "__main__":
    unittest.main()
