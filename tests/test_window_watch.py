"""Видно ли окно Chloe: закрыто ли оно другими окнами; анимация знает про паузу, покой и полный режим."""
import pathlib
import unittest

from chloe import window_watch as WW

HTML = (pathlib.Path(__file__).resolve().parent.parent / "chloe" / "ui" / "chloe-mind.html").read_text(encoding="utf-8")


class Covered(unittest.TestCase):
    def test_fully_and_partly(self):
        me = (100, 100, 400, 800)
        self.assertTrue(WW.covered(me, [(0, 0, 1920, 1080)]))                       # окно во весь экран сверху
        self.assertFalse(WW.covered(me, [(0, 0, 300, 1080)]))                        # закрыта только часть
        self.assertTrue(WW.covered(me, [(0, 0, 300, 1080), (300, 0, 1620, 1080)]))   # два окна вместе закрыли всё
        self.assertFalse(WW.covered(me, []))


class Animation(unittest.TestCase):
    def test_window_knows_view_states(self):
        self.assertIn("window.chloeView = function", HTML)
        self.assertIn('VIEW.state === "hidden"', HTML)                                # свёрнуто — кадров нет
        self.assertIn("setLite(saving", HTML)                                         # покой — меньше эффектов
        self.assertIn("var saving = calm && !VIEW.full", HTML)                        # CHLOE_ANIM=full — без экономии


class NoDisplay(unittest.TestCase):
    def test_without_x_does_nothing(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"DISPLAY": ""}):
            self.assertIsNone(WW.start(lambda st, full: True))


if __name__ == "__main__":
    unittest.main()
