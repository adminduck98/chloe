"""Пакет к публикации на YouTube: обложки (крупный текст, свободная сторона, читается маленькой), субтитры, главы, описание."""
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from chloe import publish, studio


def frame(hero_x=0.3):
    im = Image.new("RGB", (1280, 720), (20, 22, 40))
    d = ImageDraw.Draw(im)
    x = int(hero_x * 1280)
    d.ellipse((x - 30, 300, x + 30, 360), outline=(0, 255, 255), width=8)
    d.line((x, 360, x, 560), fill=(0, 255, 255), width=8)
    return im


class Cover(unittest.TestCase):
    def test_text_goes_to_the_free_side_and_is_readable_small(self):
        for hx, side in ((0.25, "right"), (0.75, "left")):
            im, cap = publish.draw_cover(frame(hx), "Курсор обнаглел", subject=(hx, 0.5))
            self.assertEqual(im.size, publish.COVER)
            self.assertTrue(publish.readable(cap))
            half = im.crop((640, 0, 1280, 720) if side == "right" else (0, 0, 640, 720))
            yellow = sum(1 for r, g, b in half.getdata() if r > 200 and g > 170 and b < 80)
            self.assertGreater(yellow, 2000, side)                       # слово-акцент — на свободной стороне

    def test_layout_picks_biggest_letters(self):
        self.assertEqual(publish.wrap("«Курсор» против человечка и ещё слова"), ["КУРСОР", "ПРОТИВ", "ЧЕЛОВЕЧКА", "И"])
        self.assertEqual(publish.layouts(["А", "Б", "В"])[-1], ["А", "Б", "В"])
        _im, short = publish.draw_cover(frame(), "Бах", subject=(0.3, 0.5))
        _im, long = publish.draw_cover(frame(), "Очень длинная надпись тут", subject=(0.3, 0.5))
        self.assertGreater(short, long)

    def test_readable_threshold(self):
        self.assertFalse(publish.readable(40))                           # 40 px из 720 → 5 px в ленте
        self.assertTrue(publish.readable(80))


class Subtitles(unittest.TestCase):
    def test_srt(self):
        self.assertEqual(publish.srt_time(3723.456), "01:02:03,456")
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        publish.write_srt([(0.0, 1.2, "Привет,"), (1.2, 2.0, "мир.")], d / "a.srt")
        self.assertEqual((d / "a.srt").read_text(encoding="utf-8").split("\n")[:3], ["1", "00:00:00,000 --> 00:00:01,200", "Привет,"])


class Package(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.scenes = [{"picture": "x", "narration": "Раз два.", "stage": st} for st in ("hook", "hook", "secret", "truth", "finale")]
        for i in range(5):
            (self.dir / "clip{:02d}.mp4".format(i)).write_bytes(b"x")
            (self.dir / "words{:02d}.json".format(i)).write_text(json.dumps([[0.0, 0.5, "Раз"], [0.5, 1.0, "два."]]))
            frame(0.2 + 0.15 * i).save(self.dir / "image{:02d}.png".format(i))
        (self.dir / "film.mp4").write_bytes(b"video")

    def test_chapters_only_for_long_films(self):
        with mock.patch.object(studio, "duration", return_value=15.0):
            self.assertEqual(publish.chapters(self.dir, self.scenes),
                             ["0:00 Начало", "0:30 Скрытая деталь", "0:45 Главное", "1:00 Финал"])
        with mock.patch.object(studio, "duration", return_value=8.0):
            self.assertEqual(publish.chapters(self.dir, self.scenes), [])     # короче минуты — без глав

    def test_package_folder(self):
        reply = json.dumps({"title": "Курсор против человечка", "description": "Человечек даёт сдачи.", "tags": ["анимация", "курсор"],
                            "hashtags": ["анимация"], "en": ["One two."] * 5})
        script = {"title": "Курсор", "cover": "Курсор обнаглел", "scenes": self.scenes}
        with mock.patch.object(studio, "duration", return_value=15.0), mock.patch.object(publish, "suggestions", return_value=["курсор мыши"]):
            out, report = publish.package(self.dir, self.dir / "film.mp4", script, mode="slides", ask=lambda text, think=False: reply)
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(names, sorted(["film.mp4", "обложка-1.jpg", "обложка-2.jpg", "обложка-3.jpg", "субтитры-ru.srt",
                                        "subtitles-en.srt", "описание.txt"]))
        text = (out / "описание.txt").read_text(encoding="utf-8")
        self.assertIn("Курсор против человечка", text)
        self.assertIn("0:00 Начало", text)                                 # главы — в описании
        self.assertIn("#анимация", text)
        self.assertIn("синтетический", text)                               # напоминание об отметке ИИ
        self.assertIn("обложек: 3", report[0])

    def test_package_without_model(self):
        def broken(text, think=False):
            raise RuntimeError("нет ключа")

        with mock.patch.object(studio, "duration", return_value=8.0), mock.patch.object(publish, "suggestions", return_value=[]):
            out, _ = publish.package(self.dir, self.dir / "film.mp4", {"title": "Курсор", "logline": "Про курсор.",
                                                                      "scenes": self.scenes}, mode="slides", ask=broken)
        self.assertIn("Про курсор.", (out / "описание.txt").read_text(encoding="utf-8"))
        self.assertFalse((out / "subtitles-en.srt").exists())             # без перевода — только русские


if __name__ == "__main__":
    unittest.main()
