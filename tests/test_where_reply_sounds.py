"""Ответ звучит там, откуда пришла просьба: с телефона — на телефоне (компьютер молчит), с компьютера — на компьютере."""
import unittest
from unittest import mock

from chloe import voice as voice_mod
from chloe.brain import brain
from chloe.signals import state
from chloe.voice import Voice


class WhereReplySounds(unittest.TestCase):
    def say(self, where):
        v = Voice(enabled=True)
        spoken, replies = [], []
        state["where"] = where
        self.addCleanup(state.__setitem__, "where", "local")
        with mock.patch.object(voice_mod, "TTS", "edge"), \
             mock.patch.object(v, "_say_edge", lambda t: spoken.append(t) or True), \
             mock.patch.object(v, "_say_piper", lambda t: spoken.append(t) or True), \
             mock.patch.object(v, "_say_pyttsx3", lambda t: spoken.append(t)), \
             mock.patch.object(brain, "js", lambda fn, *a: replies.append((fn, a))):
            v.say("Готово")
        return spoken, [a for fn, a in replies if fn == "chloeReply"]

    def test_phone_request_is_silent_on_computer(self):
        spoken, replies = self.say("phone")
        self.assertEqual(spoken, [])                                  # колонки компьютера молчат
        self.assertEqual(replies, [("Готово", "phone")])              # телефон получает текст и озвучит его

    def test_computer_request_speaks_on_computer_only(self):
        spoken, replies = self.say("local")
        self.assertEqual(spoken, ["Готово"])
        self.assertEqual(replies, [("Готово", "local")])              # телефон покажет текст, но не озвучит

    def test_phone_page_speaks_only_phone_replies(self):
        import pathlib
        js = (pathlib.Path(__file__).resolve().parent.parent / "chloe" / "ui" / "remote.js").read_text(encoding="utf-8")
        self.assertIn('if (where === "phone") say(text);', js)


if __name__ == "__main__":
    unittest.main()
