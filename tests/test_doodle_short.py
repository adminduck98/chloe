"""Мультик «Персик и Пушок»: план, слова по моментам, цена, цепочка видео (каждое — с конца предыдущего), сборка в
48 к/с со своей музыкой, отказ от «да» — ничего не тратится. Qwen подменён."""
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from chloe import doodle_short as DS
from chloe import studio
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False
PLAN = {"title": "Кофе", "scene": "A cozy cafe, Peach on the left, Puff on the right",
        "beats": [{"words": "Я люблю кофе", "seconds": 3, "motion": "Peach sips coffee happily"},
                  {"words": "а я?", "seconds": 3, "motion": "Puff turns offended"}]}


def clip(path, color, secs=3):
    subprocess.run([studio.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=%s:s=180x320:r=24:d=%d" % (color, secs),
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


class Plan(unittest.TestCase):
    def test_parse_and_limits(self):
        reply = "вот: " + json.dumps({"title": "Тест", "scene": "cafe", "beats": [
            {"words": "раз", "seconds": 9, "motion": "a"}, {"words": "два", "seconds": 1, "motion": "b"}, {"words": "", "motion": ""}]})
        p = DS.parse_plan(reply, 12)
        self.assertEqual([b["seconds"] for b in p["beats"]], [5, 3])        # 3–5 с, пустой момент выброшен
        with self.assertRaises(DS.DoodleError):
            DS.parse_plan('{"beats": []}', 12)

    def test_too_long_is_trimmed(self):
        beats = [{"words": str(i), "seconds": 5, "motion": "m"} for i in range(4)]
        p = DS.parse_plan(json.dumps({"scene": "s", "beats": beats}), 8)
        self.assertLessEqual(sum(b["seconds"] for b in p["beats"]), 15)
        self.assertEqual(p["beats"][-1]["words"], "3")                      # реакция в конце остаётся

    def test_words_inside_their_moments_and_cost(self):
        words, phrases = DS.word_times(PLAN)
        self.assertEqual([w for _, w, _ in words], ["Я", "люблю", "кофе", "а", "я?"])
        self.assertTrue(all(0 < at < 3 for at, _, ln in words if ln == 0))
        self.assertTrue(all(3 < at < 6 for at, _, ln in words if ln == 1))
        self.assertAlmostEqual(DS.cost_percent(PLAN), DS.IMAGE_PERCENT + 6 * DS.VIDEO_PERCENT_PER_SEC)


class Music(unittest.TestCase):
    def test_own_tune_has_sound_and_length(self):
        m = DS.music(4.0)
        self.assertEqual(m.shape, (int(4.0 * DS.SR), 2))
        self.assertGreater(float(np.abs(m).mean()), 0.01)


class Chain(unittest.TestCase):
    def test_each_clip_starts_from_previous_last_frame(self):
        work = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        src = work / "src"
        src.mkdir()
        made = {"t1": clip(src / "a.mp4", "red"), "t2": clip(src / "b.mp4", "blue")}
        hero_img = src / "frame.png"
        subprocess.run([studio.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=180x320", "-frames:v", "1", str(hero_img)], check=True)
        starts = []
        with mock.patch.object(DS.qm, "image", return_value=[str(hero_img)]) as draw, \
                mock.patch.object(DS.qm, "video_start", side_effect=lambda p, source, seconds: starts.append(source) or "t%d" % len(starts)), \
                mock.patch.object(DS.qm, "video_wait", side_effect=lambda task, name: str(made[task])):
            clips = DS.chain(PLAN, work, progress=lambda t: None)
            DS.chain(PLAN, work, progress=lambda t: None)                    # второй раз — готовое не переделывается
        self.assertEqual(len(clips), 2)
        self.assertEqual(draw.call_count, 1)
        self.assertEqual(len(starts), 2)
        self.assertTrue(starts[0].endswith("frame0.png"))
        self.assertTrue(starts[1].endswith("part1-last.png"))                # второе видео — с конца первого
        self.assertIn("source", draw.call_args.kwargs)                       # первый кадр — по листу героев


class Assemble(unittest.TestCase):
    def test_smooth_vertical_with_sound(self):
        work = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        clips = [clip(work / "p1.mp4", "orange"), clip(work / "p2.mp4", "purple")]
        out = DS.assemble(clips, PLAN, work / "out.mp4", work)
        info = subprocess.run([studio.ffmpeg(), "-i", str(out)], capture_output=True, text=True).stderr
        self.assertIn("1080x1920", info)
        self.assertIn("48 fps", info)
        self.assertIn("Audio", info)
        self.assertAlmostEqual(studio.duration(out), 6.0, delta=0.3)          # встык: без повторного кадра и без переходов


class Tool(unittest.TestCase):
    def test_no_yes_means_nothing_spent(self):
        with mock.patch.object(DS.qm, "available", return_value=True), \
                mock.patch.object(DS, "make_plan", return_value=PLAN), \
                mock.patch("chloe.tools.media.confirm", return_value=False) as ask, \
                mock.patch.object(DS.qm, "video_start") as vid, mock.patch.object(DS.qm, "image") as img:
            out, _, _ = run_tool("doodle_short", {"idea": "Персик любит кофе, Пушок обижается"})
        self.assertIn("% месячного пакета Qwen", ask.call_args[0][0])
        vid.assert_not_called()
        img.assert_not_called()
        self.assertIn("Не делаю", out)

    def test_needs_idea(self):
        with mock.patch.object(DS.qm, "available", return_value=True):
            out, _, _ = run_tool("doodle_short", {"idea": ""})
        self.assertIn("Нужна идея", out)


if __name__ == "__main__":
    unittest.main()
