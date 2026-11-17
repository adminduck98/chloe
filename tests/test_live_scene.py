"""Живая сцена: код строит остров (Blender), Qwen только улучшает кадр, код оживляет в петлю; выбор частиц и времени
года по пожеланию; инструмент в фоне считает одну картинку и не трогает видео-лимит."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

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


class Moves(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get(MB.KEY)
        settings.set(MB.KEY, [])

    def tearDown(self):
        settings.set(MB.KEY, self.saved)

    def test_plan_fits_five_seconds(self):
        self.assertEqual(LS.moves_plan(["wave", "jump", "dance", "walk"]), ["wave", "jump"])   # 3,6 с; ещё 2 — уже больше 5
        self.assertEqual(LS.moves_plan([]), ["idle", "wave", "jump"])
        self.assertEqual(LS.moves_plan(["fly", "dance"]), ["dance"])

    def test_code_moves_qwen_frame_vace_repaints(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)

            def fake_render(plan, season, out):
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=pink:s=72x128:d=1", str(out)], check=True)
                return Path(out)
            raw = d / "raw.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=72x128:d=1", str(raw)], check=True)
            ref = picture(d / "ref.png")
            with mock.patch.object(LS, "render_moves", side_effect=fake_render) as render, \
                    mock.patch.object(LS, "enhance", return_value=(ref, True)) as better, \
                    mock.patch.object(LS.qm, "vace_repaint", return_value="t1") as vace, \
                    mock.patch.object(LS.qm, "VIDEO_DIR", d):
                video, pic = LS.make_moves(["wave"], "остров зимой", wait=lambda task, title: raw)
            self.assertEqual(render.call_args[0][:2], (["wave"], "winter"))
            self.assertEqual(better.call_args[0][1], "winter")
            self.assertEqual(vace.call_args[0][2], ref)                   # образец — улучшенный первый кадр
            self.assertIn("headphones", vace.call_args[0][1])
            info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                                   str(video)], capture_output=True, text=True).stdout.strip()
            self.assertEqual(info, "1080,1920")

    def test_tool_respects_weekly_video_limit(self):
        MB.spend("video", 5, "неделя занята")
        with mock.patch("chloe.qwen_media.available", return_value=True), \
                mock.patch("chloe.tools.media._start", return_value=5) as start:
            out, _, _ = run_tool("live_scene", {"moves": ["wave", "jump"]})
            self.assertIn("Не делаю", out)
            start.assert_not_called()
            out, _, _ = run_tool("live_scene", {"moves": "wave, jump", "over_limit": True})
        self.assertIn("#5", out)
        self.assertIn("wave, jump", out)
