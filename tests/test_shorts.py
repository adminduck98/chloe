"""Shorts: выбор кусков, тизер, оператор, крючки, сборка вертикального ролика, инструмент make_film action=shorts."""
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from chloe import shorts as S
from chloe import studio


class Choice(unittest.TestCase):
    def test_pieces_are_whole_scenes_within_limits_and_do_not_overlap(self):
        spans = [(i * 10.0, i * 10.0 + 10) for i in range(8)]               # 8 сцен по 10 с
        en = np.full(80 * 25, 0.2)
        en[50 * 25:70 * 25] = 1.0                                           # драка — с 50-й по 70-ю секунду
        chosen = S.choose(S.candidates(spans, en), 2)
        self.assertEqual(len(chosen), 2)
        starts = {s for s, _e in spans}
        for a, b, _ in chosen:
            self.assertIn(a, starts)
            self.assertTrue(S.MIN_SECS <= b - a <= S.MAX_SECS)
        (a1, b1, _), (a2, b2, _) = chosen
        self.assertLessEqual(b1, a2)                                        # не пересекаются
        best = max(chosen, key=lambda c: c[2])
        self.assertTrue(best[0] <= 50 and best[1] >= 70)                    # лучший кусок — с дракой

    def test_short_film_is_one_whole_piece(self):
        spans = [(0.0, 9.0), (9.0, 20.0), (20.0, 31.0)]
        chosen = S.choose(S.candidates(spans, np.full(31 * 25, 0.5)), 1)
        self.assertEqual(chosen[0][:2], (0.0, 31.0))
        self.assertEqual(S.default_count(31), 1)
        self.assertEqual(S.default_count(73), 2)
        self.assertEqual(S.default_count(600), 3)

    def test_long_scene_gets_a_window(self):
        chosen = S.choose(S.candidates([(0.0, 120.0)], np.full(120 * 25, 0.4)), 1)
        self.assertAlmostEqual(chosen[0][1] - chosen[0][0], S.MAX_SECS)


class Teaser(unittest.TestCase):
    def test_calm_start_gets_the_brightest_moment(self):
        en = np.full(30 * 25, 0.1)
        en[20 * 25:22 * 25] = 1.0
        t = S.teaser_at(en, 0.0, 30.0)
        self.assertTrue(19.5 <= t <= 21.5)

    def test_busy_start_needs_no_teaser(self):
        self.assertIsNone(S.teaser_at(np.full(30 * 25, 0.8), 0.0, 30.0))

    def test_teaser_only_where_hero_is_seen(self):
        en = np.full(30 * 25, 0.1)
        en[20 * 25:22 * 25] = 1.0                                           # ярко, но героя нет (исчез в портале)
        en[10 * 25:12 * 25] = 0.6
        t = S.teaser_at(en, 0.0, 30.0, seen=lambda x: not (19 <= x <= 23))
        self.assertTrue(9.5 <= t <= 11.5)


class Camera(unittest.TestCase):
    def test_follows_and_widens(self):
        narrow = 1080 * 9 / 16
        near = [(0.1, 0.5, 0.15, 0.9)] * 120                               # один герой слева
        far = [(0.1, 0.5, 0.9, 0.9)] * 50                                  # двое на весь кадр
        cams = S.camera(near + far, (0.0, 1.0))
        cx0, cw0 = cams[20]
        self.assertAlmostEqual(cw0, narrow, delta=1)
        self.assertTrue(cw0 / 2 <= cx0 <= 1920 * 0.25)                     # рамка у героя, но не за краем кадра
        self.assertGreater(cams[-1][1], 1920 * 0.9)                        # разошлись — отъезд почти на весь кадр
        self.assertTrue(all(c[0] - c[1] / 2 >= -0.5 and c[0] + c[1] / 2 <= 1920.5 for c in cams))

    def test_no_heroes_means_whole_frame(self):
        self.assertEqual(S.camera([None] * 10, (0.0, 1.0))[0], (960.0, 1920.0))

    def test_burnt_captions_stay_outside(self):
        self.assertEqual(S.caption_band("action", False), (0.0, 1.0))
        self.assertLess(S.caption_band("action", True)[1], 0.9)
        self.assertGreater(S.caption_band("neon_desktop", True)[0], 0.1)    # у неона субтитры сверху


class Text(unittest.TestCase):
    def test_preposition_moves_to_next_line(self):
        import cairo

        c = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 10, 10))
        S._font(c, 124)
        lines = S.wrap_words(c, "Затянуло в игру".split(), 1080 * S.SAFE_W)
        self.assertTrue(all(len(line[-1]) > 2 for line in lines[:-1]))

    def test_hooks_from_model_and_fallbacks(self):
        script = {"title": "Затянуло в игру", "cover": "Нажал Play", "logline": "x"}
        reply = json.dumps({"hooks": ["Он нажал не ту кнопку", "это слишком длинная надпись которую никто не прочитает"]})
        hooks = S.hook_texts(script, ["a", "b"], ask=lambda text, think=False: reply)
        self.assertEqual(hooks[0], "Он нажал не ту кнопку")
        self.assertIn(hooks[1], ("Нажал Play", "Затянуло в игру"))           # длинная — заменена надписью из сценария

        def broken(text, think=False):
            raise RuntimeError("нет модели")
        self.assertEqual(S.hook_texts(script, ["a"], ask=broken), ["Нажал Play"])
        self.assertEqual(S.accent_word("Он нажал не ту кнопку"), "кнопку")


class Tracking(unittest.TestCase):
    def test_walking_hero_is_followed(self):
        spec = {"actors": [{"id": "hero", "x": 0.15}], "acting": [{"who": "hero", "do": "walk", "from": 0.0, "to": 1.0, "x": 0.85}]}
        boxes = S.track_anim(spec, "classic_light", 3.0)
        self.assertEqual(len(boxes), 75)
        self.assertTrue(all(b is not None for b in boxes))
        mid = [(b[0] + b[2]) / 2 for b in boxes]
        self.assertLess(mid[5], 0.35)
        self.assertGreater(mid[-5], 0.65)


def _clip(path, secs, color, size="1920x1080"):
    subprocess.run([studio.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c={}:s={}:r=25:d={}".format(color, size, secs),
                    "-f", "lavfi", "-i", "sine=frequency=440:duration={}".format(secs), "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)


class Build(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_vertical_short_with_hook_and_notes(self):
        for i, col in enumerate(("red", "blue")):
            _clip(self.dir / "clip{:02d}.mp4".format(i), 2, col)
        studio.join([self.dir / "clip00.mp4", self.dir / "clip01.mp4"], self.dir / "film.mp4")
        script = {"title": "Проба", "cover": "Смотри что будет", "logline": "Проба Shorts.",
                  "scenes": [{"picture": "a", "narration": ""}, {"picture": "b", "narration": ""}]}
        with mock.patch.object(S, "MIN_SECS", 1.0):
            made = S.make_shorts(self.dir, self.dir / "film.mp4", script, mode="slides", ask=False, out_dir=self.dir / "out",
                                 progress=lambda t: None)
        self.assertEqual(len(made), 1)
        path = made[0][0]
        self.assertEqual(S.video_size(path), (1080, 1920))
        self.assertAlmostEqual(studio.duration(path), 4.0, delta=0.3)
        notes = (self.dir / "out" / "shorts.txt").read_text(encoding="utf-8")
        self.assertIn("#Shorts", notes)
        self.assertIn("Связанное видео", notes)

    def test_vertical_film_is_already_a_short(self):
        _clip(self.dir / "clip00.mp4", 1, "red", "1080x1920")
        with self.assertRaises(S.ShortsError):
            S.make_shorts(self.dir, self.dir / "clip00.mp4", {"scenes": [{"picture": "a"}]}, ask=False)


class Tool(unittest.TestCase):
    def test_needs_finished_film(self):
        from chloe.tools import media

        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(studio, "load_project", return_value={"folder": tmp, "title": "Проба", "scenes": []}):
            self.assertIn("ещё не доделан", media.tool_make_film({"action": "shorts"}))


if __name__ == "__main__":
    unittest.main()
