"""Связка Qwen + Хлоя (без кредитов: Qwen подменён): словарь камеры, задание видео под длину клипа, лист героя,
кадры по нему, звуки по движению в готовом клипе."""
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

from chloe import motion_words as MW
from chloe import qwen_media as qm
from chloe import screenplay as sp
from chloe import studio


def has_ffmpeg():
    try:
        studio.ffmpeg()
        return True
    except studio.StudioError:
        return False


class Words(unittest.TestCase):
    def test_find_by_key_or_russian_words(self):
        self.assertEqual(MW.find("orbit"), "orbit")
        self.assertEqual(MW.find("сделай наезд на героя"), "dolly_in")
        self.assertEqual(MW.find("снимай с дрона"), "fpv")
        self.assertIsNone(MW.find("как-нибудь"))
        self.assertIn("dolly in", MW.phrase("dolly_in"))

    def test_timeline_fits_the_real_length(self):
        out = MW.fit_timeline("[0–3s] he walks, [3–6s] he jumps", 9.0)
        self.assertEqual(out, "[0.0–4.5s] he walks, [4.5–9.0s] he jumps")
        self.assertEqual(MW.fit_timeline("no stamps", 9.0), "no stamps")

    def test_video_prompt(self):
        p = MW.video_prompt({"video": "[0–2s] runs [2–4s] falls", "camera_move": "tracking", "angle": "low"}, 8)
        self.assertIn("tracking shot", p)
        self.assertIn("low angle", p)
        self.assertIn("[4.0–8.0s] falls", p)
        self.assertIn("exactly as in the first frame", p)

    def test_scriptwriter_gets_the_dictionary_for_live_video(self):
        self.assertIn("camera_move", sp.prompt("видео", duration=40))
        self.assertIn("dolly_in", sp.prompt("видео", duration=40))
        self.assertNotIn("CAMERA_GUIDE", sp.prompt("видео", duration=40, anim=True))
        self.assertEqual(studio.clean_scenes([{"picture": "x", "camera_move": "orbit"}])[0]["camera_move"], "orbit")


class Hero(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "img.png").write_bytes(b"png")

    def test_sheet_once_and_scenes_from_it(self):
        calls = []

        def image(prompt, ratio="1:1", n=1, source=None, model=None):
            calls.append((prompt, source))
            return [self.dir / "img.png"]

        with mock.patch.object(qm, "image", side_effect=image):
            hero = studio.hero_sheet(self.dir, [{"picture": "x"}], "", "16:9", "classic_light")
            again = studio.hero_sheet(self.dir, [{"picture": "x"}], "", "16:9", "classic_light")
        self.assertEqual(hero, again)
        self.assertEqual(len(calls), 1)                                    # лист героя — один раз на ролик
        self.assertIn("reference sheet", calls[0][0])
        self.assertIn("stick figure", calls[0][0])                         # паспорт героя стиля — в листе

    def test_sheet_failure_is_not_fatal(self):
        with mock.patch.object(qm, "image", side_effect=qm.MediaError("нет кредитов")):
            self.assertIsNone(studio.hero_sheet(self.dir, [{"picture": "x"}], "", "16:9", None))

    def test_estimate_counts_the_sheet(self):
        scenes = [{"picture": "x", "narration": "a" * 70}] * 2
        self.assertAlmostEqual(studio.estimate(scenes, "slides"), 3 * studio.SLIDE_COST)


class Frame(unittest.TestCase):
    def test_portrait_picture_fits_a_wide_frame_whole(self):
        from PIL import Image

        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        Image.new("RGB", (880, 1176), (0, 160, 220)).save(d / "p.png")
        out = studio.fit_frame(d / "p.png", (1920, 1080))
        im = Image.open(out)
        self.assertEqual(im.size, (1280, 720))
        self.assertEqual(im.getpixel((640, 10)), (0, 160, 220))          # картинка целиком по центру, без обрезки
        Image.new("RGB", (1664, 928)).save(d / "w.png")
        self.assertEqual(studio.fit_frame(d / "w.png", (1920, 1080)), d / "w.png")   # та же форма — как есть

    def test_scene_pictures_ask_for_the_frame_shape(self):
        sent = []

        def http(method, path, body=None, headers=None, timeout=120):
            sent.append(body)
            return {"output": {"choices": [{"message": {"content": [{"image": "https://x/a.png"}]}}]}}

        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "h.png").write_bytes(b"\x89PNG")
        with mock.patch.object(qm, "_http", side_effect=http), mock.patch.object(qm, "_save", return_value=d / "a.png"):
            qm.image("сцена", "16:9", source=str(d / "h.png"))
            qm.image("сделай фон синим", source=str(d / "h.png"))
        self.assertIn("size", sent[0]["parameters"])                     # сцена ролика — нужной формы
        self.assertNotIn("size", sent[1]["parameters"])                  # правка картинки — её форма

    def test_size_refused_then_without_it(self):
        calls = []

        def http(method, path, body=None, headers=None, timeout=120):
            calls.append(dict(body["parameters"]))
            if len(calls) == 1:
                raise qm.MediaError("Alibaba: InvalidParameter size")
            return {"output": {"choices": [{"message": {"content": [{"image": "https://x/a.png"}]}}]}}

        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "h.png").write_bytes(b"\x89PNG")
        with mock.patch.object(qm, "_http", side_effect=http), mock.patch.object(qm, "_save", return_value=d / "a.png"):
            qm.image("сцена", "16:9", source=str(d / "h.png"))
        self.assertEqual(["size" in c for c in calls], [True, False])


class MotionSounds(unittest.TestCase):
    def test_flash_means_impact_even_inside_a_jump(self):
        e = np.full(250, 0.01)
        e[130] = 0.09                                                      # 5,2 с — посреди прыжка
        scene = {"video": "[0–3s] the cursor swoops [3–5s] he dodges with a jump [5–8s] he punches the cursor"}
        self.assertEqual(studio.motion_events(e, scene)[0]["kind"], "thud")             # по словам — прыжок
        self.assertEqual(studio.motion_events(e, scene, flashes=[5.2])[0]["kind"], "punch")    # но это вспышка удара

    def test_spikes_become_sounds_by_script_words(self):
        e = np.full(250, 0.01)
        e[50], e[150], e[200] = 0.12, 0.1, 0.6                              # удар, падение, склейка
        scene = {"video": "[0–3s] he punches the robot [3–6s] he falls down [6–10s] calm"}
        ev = studio.motion_events(e, scene)
        self.assertEqual([(x["t"], x["kind"]) for x in ev], [(2.0, "punch"), (6.0, "thud")])

    def test_quiet_clip_has_no_sounds(self):
        self.assertEqual(studio.motion_events(np.full(100, 0.01), {"video": "walks"}), [])

    @unittest.skipUnless(has_ffmpeg(), "нет ffmpeg")
    def test_real_clip_motion_and_track(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        clip = d / "c.mp4"                                                   # белый квадрат резко прыгает на 2-й секунде
        studio.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=320x180:d=4:r=25", "-vf",
                           "drawbox=x=40:y=60:w=60:h=60:color=white:t=fill:enable='lt(t,2)',"
                           "drawbox=x=200:y=60:w=60:h=60:color=white:t=fill:enable='gte(t,2)'", "-pix_fmt", "yuv420p", clip])
        energy = studio.video_motion(clip)
        self.assertAlmostEqual(int(np.argmax(energy)) / 25, 2.0, delta=0.08)
        track = studio.motion_sounds(clip, {"video": "[0–4s] he gets hit"}, 4.0, d / "s.wav", transition=True)
        self.assertTrue(pathlib.Path(track).exists())


if __name__ == "__main__":
    unittest.main()
