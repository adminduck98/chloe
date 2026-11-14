"""Рисованный стиль «Персик и Пушок»: находится по словам пользователя, у него готовый лист героев — по нему Qwen рисует
каждую сцену, а сам лист не рисуется и не оплачивается заново."""
import pathlib
import tempfile
import unittest
from unittest import mock

from chloe import stickman_styles as ST
from chloe import studio


class Doodle(unittest.TestCase):
    def test_found_by_words(self):
        for words in ("в рисованном стиле", "с Персиком и Пушком", "карандашом", "как скетч", "doodle"):
            self.assertEqual(ST.find(words), "doodle", words)
        self.assertEqual(ST.find("в тёмном стиле"), "classic_dark")      # старые стили не задеты

    def test_has_ready_hero_sheet(self):
        p = ST.hero_file("doodle")
        self.assertIsNotNone(p)
        self.assertGreater(p.stat().st_size, 10000)
        self.assertIsNone(ST.hero_file("classic_light"))

    def test_hero_sheet_copied_not_drawn(self):
        work = pathlib.Path(tempfile.mkdtemp())
        with mock.patch.object(studio.qm, "image") as draw:
            path = studio.hero_sheet(work, [{"picture": "кафе"}], "", "9:16", "doodle")
        draw.assert_not_called()
        self.assertEqual(path.read_bytes(), ST.hero_file("doodle").read_bytes())

    def test_frame_describes_both_heroes_and_paper(self):
        text = ST.frame("They sit in a cafe", "doodle")
        self.assertIn("Peach", text)
        self.assertIn("Puff", text)
        self.assertIn("colored-pencil", text)
        self.assertIn("doodle", ST.catalog())


if __name__ == "__main__":
    unittest.main()
