"""Громкость и яркость. Настоящий звук и экран не трогаются: pactl и gdbus подменены."""
import re
import unittest
from unittest import mock

from chloe import config
from chloe.thinking.router import Route
from chloe.tools import controls, run_tool
from chloe.voice import voice

voice.enabled = False


class FakeLinux:
    """Изображает pactl и Cinnamon: хранит громкость, выключен ли звук и яркость."""

    def __init__(self, cinnamon=True):
        self.volume, self.muted, self.bright, self.cinnamon = 40, False, 60, cinnamon

    def run(self, cmd, timeout=5):
        if cmd[0] == "pactl":
            if cmd[1] == "get-sink-volume":
                return "Volume: front-left: 1 / {0}% / -1 dB, front-right: 1 / {0}% / -1 dB".format(self.volume)
            if cmd[1] == "get-sink-mute":
                return "Mute: " + ("yes" if self.muted else "no")
            if cmd[1] == "set-sink-volume":
                self.volume = int(cmd[3].rstrip("%"))
                return ""
            if cmd[1] == "set-sink-mute":
                self.muted = cmd[3] == "1"
                return ""
        if cmd[0] == "gdbus" and "cinnamon" in cmd[4] and self.cinnamon:
            if cmd[-1].endswith("GetPercentage"):
                return "(uint32 {},)".format(self.bright)
            if cmd[-2].endswith("SetPercentage"):
                self.bright = int(cmd[-1])
                return "(uint32 {},)".format(self.bright)
        raise RuntimeError("нет такой службы")


class Controls(unittest.TestCase):
    def setUp(self):
        self.pc = FakeLinux()
        for target, value in ((controls, "run"), (controls, "OS_NAME")):
            p = mock.patch.object(target, value, self.pc.run if value == "run" else "Linux")
            p.start()
            self.addCleanup(p.stop)

    def test_volume_report_and_set(self):
        self.assertEqual(run_tool("volume", {})[0], "Громкость 40%.")
        run_tool("volume", {"level": 75})
        self.assertEqual(self.pc.volume, 75)
        run_tool("volume", {"change": -20})
        self.assertEqual(self.pc.volume, 55)

    def test_volume_stays_in_0_100(self):
        run_tool("volume", {"change": 500})
        self.assertEqual(self.pc.volume, 100)   # не 540% — колонки не порвёт
        run_tool("volume", {"level": -3})
        self.assertEqual(self.pc.volume, 0)

    def test_mute_and_louder_unmutes(self):
        out = run_tool("volume", {"mute": True})[0]
        self.assertTrue(self.pc.muted)
        self.assertIn("только текстом", out)   # модель знает, что её не услышат
        run_tool("volume", {"change": 10})   # «сделай погромче»
        self.assertFalse(self.pc.muted)
        self.assertEqual(self.pc.volume, 50)

    def test_brightness_reads_percent_not_type(self):
        self.assertEqual(run_tool("brightness", {})[0], "Яркость 60%.")   # не 32 из «uint32»

    def test_brightness_change_and_floor(self):
        run_tool("brightness", {"change": 15})
        self.assertEqual(self.pc.bright, 75)
        out = run_tool("brightness", {"level": 0})[0]
        self.assertEqual(self.pc.bright, controls.MIN_BRIGHTNESS)   # экран не гаснет совсем
        self.assertIn("не погас", out)

    def test_no_brightness_control_is_honest(self):
        self.pc.cinnamon = False
        with mock.patch.object(controls.shutil, "which", return_value=None):
            out, _, failed = run_tool("brightness", {"level": 50})
        self.assertTrue(failed)
        self.assertTrue(re.match("Не могу", out))

    def test_simple_job_for_fast_brain(self):
        config.MODEL_FAST, config.MODEL_STRONG = "fast-model", "strong-model"
        for text in ("сделай погромче", "убавь яркость", "выключи звук"):
            r = Route(text)
            self.assertEqual(r.model, "fast-model", text)
            self.assertFalse(r.redo_for(["volume", "brightness"]))


if __name__ == "__main__":
    unittest.main()
