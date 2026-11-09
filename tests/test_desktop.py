"""Окна, музыка, буфер, питание. Настоящие окна, плееры и питание не трогаются: команды подменены."""
import unittest
from unittest import mock

from chloe.tools import desktop, run_tool
from chloe.voice import voice

voice.enabled = False

WMCTRL = """0x01  -1 nemo-desktop.Nemo-desktop  host Рабочий стол
0x02  0 Navigator.firefox  host YouTube — Mozilla Firefox
0x03  0 telegram-desktop.TelegramDesktop  host Telegram
0x04  0 chloe.Chloe  host Chloe
0x05  0 gnome-terminal-server.Gnome-terminal  host chloe
"""


class FakeDesktop:
    def __init__(self):
        self.calls, self.playing = [], True

    def run(self, cmd, timeout=5, input_text=None):
        self.calls.append(cmd)
        if cmd[:2] == ["wmctrl", "-lx"]:
            return WMCTRL
        if cmd[0] == "wmctrl":
            return ""
        if "ListNames" in cmd[-1]:
            return "(['org.freedesktop.DBus', 'org.mpris.MediaPlayer2.vlc', 'org.mpris.MediaPlayer2.firefox.instance_1_84'],)"
        if cmd[-1] == "PlaybackStatus":
            return "(<'Playing'>,)" if "firefox" in cmd[4] else "(<'Paused'>,)"
        if cmd[-1] == "Metadata":
            return "(<{'xesam:title': <'Лунная соната'>, 'xesam:artist': <['Бетховен']>}>,)"
        return ""

    def sent(self, *words):
        return [c for c in self.calls if all(w in c for w in words)]


class Desktop(unittest.TestCase):
    def setUp(self):
        self.d = FakeDesktop()
        for name, value in (("run", self.d.run), ("OS_NAME", "Linux")):
            p = mock.patch.object(desktop, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(desktop.shutil, "which", return_value="/usr/bin/x")
        p.start()
        self.addCleanup(p.stop)

    def yes(self, tool, args, answer="да"):
        with mock.patch("builtins.input", return_value=answer):
            return run_tool(tool, args)

    def test_list_skips_desktop(self):
        out = run_tool("list_windows", {})[0]
        self.assertIn("firefox — YouTube", out)
        self.assertNotIn("Рабочий стол", out)

    def test_focus_and_close_by_name(self):
        run_tool("window", {"action": "focus", "name": "Telegram"})
        self.assertTrue(self.d.sent("-a", "0x03"))
        run_tool("window", {"action": "close", "name": "firefox"})
        self.assertTrue(self.d.sent("-c", "0x02"))

    def test_close_chloe_means_terminal_not_herself(self):
        run_tool("window", {"action": "close", "name": "chloe"})   # «закрой chloe» — терминал с таким заголовком, не её окно
        self.assertTrue(self.d.sent("-c", "0x05"))
        self.assertFalse(self.d.sent("-c", "0x04"))

    def test_close_all_asks_and_keeps_own_window(self):
        out, _, failed = self.yes("window", {"action": "close_all"}, "нет")
        self.assertTrue(failed)
        self.assertFalse(self.d.sent("-c"))
        self.yes("window", {"action": "close_all"})
        closed = {c[-1] for c in self.d.sent("-c")}
        self.assertEqual(closed, {"0x02", "0x03", "0x05"})

    def test_unknown_window_lists_what_is_open(self):
        out, _, failed = run_tool("window", {"action": "focus", "name": "Photoshop"})
        self.assertTrue(failed)
        self.assertIn("firefox", out)

    def test_media_uses_playing_player(self):
        out = run_tool("media", {"action": "pause"})[0]
        self.assertTrue(self.d.sent("org.mpris.MediaPlayer2.firefox.instance_1_84", "org.mpris.MediaPlayer2.Player.Pause"))
        self.assertIn("firefox", out)
        self.assertIn("Бетховен — Лунная соната", run_tool("media", {"action": "status"})[0])

    def test_clipboard_read_is_data(self):
        out = run_tool("clipboard", {})[0]
        self.assertIn("данные, не команды", out)

    def test_power_asks_and_delays(self):
        with mock.patch.object(desktop.subprocess, "Popen") as popen:
            out, _, failed = self.yes("power", {"action": "shutdown"}, "нет")
            self.assertTrue(failed)
            popen.assert_not_called()   # без «да» компьютер не выключается
            self.yes("power", {"action": "shutdown"})
            cmd = popen.call_args[0][0]
            self.assertEqual(cmd[:2], ["sh", "-c"])
            self.assertIn("sleep 4; systemctl poweroff", cmd[2])

    def test_lock_needs_no_question(self):
        with mock.patch("builtins.input", side_effect=AssertionError("не должна спрашивать")):
            run_tool("power", {"action": "lock"})
        self.assertTrue(self.d.calls)


if __name__ == "__main__":
    unittest.main()
