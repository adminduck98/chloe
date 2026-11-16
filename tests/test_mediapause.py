"""Пауза перед важным сообщением: играет — пауза, сказать, продолжить; что было на паузе — не трогать."""
import unittest
from unittest import mock

from chloe import mediapause as MP


class Pause(unittest.TestCase):
    def test_pause_say_resume_only_playing(self):
        calls, said = [], []
        state = {"org.mpris.MediaPlayer2.firefox.instance_1": "Playing", "org.mpris.MediaPlayer2.vlc": "Paused"}

        def gdbus(*args):
            args = list(args)
            if "org.freedesktop.DBus.ListNames" in args:
                return "(['org.freedesktop.DBus', %s],)" % ", ".join("'%s'" % n for n in state)
            name = args[args.index("--dest") + 1]
            if "org.freedesktop.DBus.Properties.Get" in args:
                return "(<'%s'>,)" % state[name]
            calls.append((name, args[-1].rsplit(".", 1)[-1]))
            return "()"
        with mock.patch.object(MP, "_gdbus", side_effect=gdbus), mock.patch.object(MP.shutil, "which", return_value="/usr/bin/gdbus"):
            MP.announce(lambda t: said.append((t, list(calls))), "Мультик готов")
        self.assertEqual(said[0][1], [("org.mpris.MediaPlayer2.firefox.instance_1", "Pause")])   # пауза — до слов
        self.assertEqual(calls[-1], ("org.mpris.MediaPlayer2.firefox.instance_1", "Play"))       # потом — продолжить
        self.assertNotIn(("org.mpris.MediaPlayer2.vlc", "Play"), calls)                           # своё на паузе не трогаем

    def test_without_gdbus_just_says(self):
        said = []
        with mock.patch.object(MP.shutil, "which", return_value=None):
            MP.announce(said.append, "Напоминание")
        self.assertEqual(said, ["Напоминание"])


if __name__ == "__main__":
    unittest.main()
