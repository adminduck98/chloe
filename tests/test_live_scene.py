"""Живая сцена: код строит остров (Blender), Qwen только улучшает кадр, код оживляет в петлю; выбор частиц и времени
года по пожеланию; инструмент в фоне считает одну картинку и не трогает видео-лимит."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

from chloe import live_scene as LS
from chloe import media_budget as MB
from chloe.settings import settings
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False


def picture(path, w=225, h=400):
    Image.fromarray((np.random.default_rng(1).random((h, w, 3)) * 255).astype(np.uint8)).save(path)
    return Path(path)


class Choice(unittest.TestCase):
    def test_particles_and_season_follow_the_wish(self):
        self.assertEqual(LS.particles_for("остров зимой"), "snow")
        self.assertEqual(LS.particles_for("осенний остров"), "leaves")
        self.assertEqual(LS.particles_for("ночью"), "stars")
        self.assertEqual(LS.particles_for(""), "petals")
        self.assertEqual(LS.particles_for("зимой", "none"), "none")
        self.assertEqual(LS.SEASON_OF["snow"], "winter")

    def test_enhance_keeps_layout_and_uses_the_sample(self):
        self.assertIn("Keep from image 1", LS.ENHANCE)
        self.assertIn("quality and style sample", LS.ENHANCE)
        self.assertTrue(LS.SAMPLE.exists())

    def test_season_check(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            snow, green = d / "snow.png", d / "green.png"
            Image.new("RGB", (64, 112), (240, 244, 250)).save(snow)
            Image.new("RGB", (64, 112), (90, 170, 80)).save(green)
            self.assertTrue(LS.season_kept(snow, snow, "winter"))
            self.assertFalse(LS.season_kept(snow, green, "winter"))
            self.assertTrue(LS.season_kept(green, snow, "spring"))        # цветения не было — не проверяем


class Pipeline(unittest.TestCase):
    def test_code_builds_qwen_enhances_code_animates(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            built = picture(d / "built.png")
            better = d / "better.png"
            Image.open(built).save(better)                              # Qwen не поменял сцену
            with mock.patch.object(LS, "render_island", return_value=built) as render, \
                    mock.patch.object(LS.qm, "image", return_value=[better]) as qwen, \
                    mock.patch.object(LS.qm, "VIDEO_DIR", d), mock.patch.object(LS.qm, "IMAGE_DIR", d):
                video, pic = LS.make("остров зимой", seconds=1)
            self.assertEqual(render.call_args[0][0], "winter")
            self.assertEqual(qwen.call_args.kwargs["source"], str(built))       # Qwen получает наш кадр
            self.assertEqual(qwen.call_args.kwargs["refs"], (str(LS.SAMPLE),))  # и образец качества
            self.assertEqual(pic, better)
            info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,nb_frames", "-of",
                                   "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
            self.assertEqual(info, "1080,1920,30")

    def test_qwen_that_changes_the_scene_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ours = d / "ours.png"
            Image.new("RGB", (225, 400), (240, 244, 250)).save(ours)    # снег
            other = d / "other.png"
            Image.new("RGB", (225, 400), (90, 170, 80)).save(other)     # зелень — зима стала летом
            with mock.patch.object(LS.qm, "image", return_value=[other]) as qwen:
                pic, ok = LS.enhance(ours, "winter")
            self.assertEqual((pic, ok), (ours, False))                  # остался кадр кода
            self.assertEqual(qwen.call_count, 2)                        # попробовал ещё раз
            self.assertIn("WINTER", qwen.call_args[0][0])

    def test_without_qwen_it_is_free(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            own = picture(d / "own.png")
            with mock.patch.object(LS.qm, "image") as qwen, mock.patch.object(LS.qm, "VIDEO_DIR", d), \
                    mock.patch.object(LS.qm, "IMAGE_DIR", d):
                video, pic = LS.make("", seconds=1, source=own, better=False)
            qwen.assert_not_called()
            self.assertEqual(pic, own)
            self.assertTrue(video.exists())


class Tool(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get(MB.KEY)
        settings.set(MB.KEY, [])

    def tearDown(self):
        settings.set(MB.KEY, self.saved)

    def test_starts_in_background_and_counts_one_picture(self):
        MB.spend("video", 5, "неделя уже занята")                      # видео-лимит не мешает: это картинка
        with mock.patch("chloe.qwen_media.available", return_value=True), \
                mock.patch("chloe.tools.media._start", return_value=3) as start:
            out, _, _ = run_tool("live_scene", {"idea": "остров зимой"})
        self.assertIn("#3", out)
        self.assertIn("Blender", out)
        self.assertEqual(start.call_args[0][0], "live")
        self.assertEqual([e for e in settings.get(MB.KEY) if e.get("kind") == "image"][0]["percent"], 0.3)

    def test_free_mode_spends_nothing(self):
        with mock.patch("chloe.tools.media._start", return_value=4):
            out, _, _ = run_tool("live_scene", {"enhance": False})
        self.assertIn("#4", out)
        self.assertEqual([e for e in settings.get(MB.KEY) if e.get("kind") == "image"], [])

    def test_missing_own_picture(self):
        out, _, _ = run_tool("live_scene", {"image": "/нет/такой.png"})
        self.assertIn("Не нахожу", out)


if __name__ == "__main__":
    unittest.main()


class Heroine(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get(MB.KEY)
        settings.set(MB.KEY, [])

    def tearDown(self):
        settings.set(MB.KEY, self.saved)

    def test_moves_plan(self):
        from chloe import heroine3d as H3

        steps, total = H3.plan(["wave", "jump", "fly", "turn"])
        self.assertEqual([m for m, _, _ in steps], ["wave", "jump", "turn"])
        self.assertAlmostEqual(total, 5.6)
        blender_side = (Path(LS.__file__).parent / "blender" / "hero3d.py").read_text()
        for m, sec in H3.SECONDS.items():                                     # длины совпадают с позами в Blender
            self.assertIn('"{}": {}'.format(m, sec), blender_side)

    def test_place_and_heroine_are_separate(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            place = picture(d / "place.png", 93, 166)
            hero = d / "v000.png"
            Image.new("RGBA", (46, 83), (0, 0, 0, 0)).save(hero)
            with mock.patch.object(LS, "render_place", return_value=(place, {})) as render, \
                    mock.patch.object(LS, "enhance", return_value=(place, True)) as better, \
                    mock.patch.object(LS, "render_heroine", return_value=[hero]) as h3, \
                    mock.patch.object(LS.qm, "VIDEO_DIR", d), mock.patch.object(LS.qm, "IMAGE_DIR", d), \
                    mock.patch("chloe.heroine3d.SECONDS", {"wave": 0.4}):
                video, pic = LS.make_with_heroine(["wave"], "остров зимой")
            self.assertEqual(render.call_args[0][0], "winter")
            self.assertEqual(better.call_args[0][2], LS.PLACE_TEXT)       # место улучшают без героини
            self.assertEqual(h3.call_args[0][:2], (["wave"], "winter"))   # героиня — в том же времени года и свете

            info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                                   str(video)], capture_output=True, text=True).stdout.strip()
            self.assertEqual(info, "1080,1920")

    def test_shadow_only_near_feet(self):
        rgba = np.zeros((200, 100, 4), np.uint8)
        rgba[60:150, 40:60] = (240, 240, 250, 255)                       # героиня
        rgba[150:158, 30:70, 3] = 120                                     # её тень у ног
        rgba[10:40, 5:15, 3] = 120                                        # чужая тень далеко — убрать
        out = LS.clean_heroine(rgba)
        self.assertGreater(out[153, 50, 3], 60)
        self.assertEqual(out[20, 10, 3], 0)
        self.assertEqual(out[100, 50, 3], 255)

    def test_heroine_follows_the_island_qwen_moved(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            sky = (200, 160, 200)

            def island(path, x0, y0, x1, y1):
                im = Image.new("RGB", (232, 416), sky)
                ImageDraw.Draw(im).rectangle([x0, y0, x1, y1], fill=(80, 190, 70))   # трава
                im.save(path)
            island(d / "a.png", 20, 150, 210, 250)
            island(d / "b.png", 40, 230, 135, 280)                        # Qwen уменьшил вдвое и опустил остров
            spot = {"x": 0.5, "y": 0.5, "top": 0.3}
            moved = LS.follow_spot(spot, d / "a.png", d / "b.png", "spring")
            self.assertAlmostEqual(moved["x"], (40 + (116 - 20) * 0.5) / 232, delta=0.02)
            self.assertGreater(moved["y"], 0.5)
            self.assertAlmostEqual(moved["y"] - moved["top"], 0.1, delta=0.01)   # и рост вдвое меньше
            Image.new("RGB", (232, 416), sky).save(d / "c.png")
            self.assertEqual(LS.follow_spot(spot, d / "a.png", d / "c.png", "spring"), spot)   # не нашёл — как было

    def test_tool_counts_one_picture_and_no_video_limit(self):
        MB.spend("video", 5, "неделя занята")
        with mock.patch("chloe.qwen_media.available", return_value=True), \
                mock.patch("chloe.tools.media._start", return_value=5) as start:
            out, _, _ = run_tool("live_scene", {"moves": "wave, jump"})
        self.assertIn("#5", out)
        self.assertIn("wave, jump", out)
        self.assertEqual(start.call_args[0][0], "live")
        self.assertEqual([e["percent"] for e in settings.get(MB.KEY) if e.get("kind") == "image"], [0.3])


if __name__ == "__main__":
    unittest.main()
