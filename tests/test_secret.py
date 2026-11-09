"""Ключи и пароли: не запоминаются, не попадают в журнал, терминал и речь. Ключи в тесте выдуманные."""
import io
import json
import unittest
from contextlib import redirect_stdout

from chloe.journal import journal
from chloe.memory import memory
from chloe.secret import has_secret, redact
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False
FAKE = "sk-" + "0123456789abcdef" * 2          # похоже на ключ DeepSeek, но выдуманный
GOOGLE = "AIza" + "B" * 35


class Secrets(unittest.TestCase):
    def test_detects_and_masks(self):
        for text in (FAKE, GOOGLE, 'export DEEPSEEK_API_KEY="%s"' % FAKE, "пароль: Qwerty12345",
                     "123456789:" + "A" * 35):
            self.assertTrue(has_secret(text), text)
            self.assertNotIn(text.split()[-1].strip('"'), redact(text))
        for text in ("Запомни: я живу в Ташкенте", "max_tokens=1500", "Ключ от дома под ковриком"):
            self.assertFalse(has_secret(text), text)
            self.assertEqual(redact(text), text)

    def test_remember_refuses_keys(self):
        before = len(memory.items)
        out, _, failed = run_tool("remember", {"text": "DeepSeek API-ключ: " + FAKE})
        self.assertTrue(failed)
        self.assertEqual(len(memory.items), before)
        self.assertNotIn(FAKE, out)

    def test_journal_and_terminal_and_voice_hide_keys(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            eid = journal.add("tool", "Компьютер", "run_command: echo " + FAKE, {"args": {"command": FAKE}})
            voice.say("Ваш ключ " + FAKE)
            run_tool("forget", {"id": 999999, "note": FAKE})   # аргументы инструмента печатаются в терминал
        self.assertNotIn(FAKE, buf.getvalue())
        row = journal.db.execute("SELECT title, detail FROM events WHERE id = ?", (eid,)).fetchone()
        self.assertNotIn(FAKE, row[0] + row[1])
        self.assertNotIn(FAKE, json.dumps([tuple(r) for r in journal.db.execute("SELECT title, detail FROM events")],
                                          ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
