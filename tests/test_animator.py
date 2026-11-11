"""Свой мультипликатор: скелет, движения, синонимы, перемещение, кадры, сцены без движений, цена и режим anim."""
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from chloe import animator as A
from chloe import screenplay as sp
from chloe import studio

SPEC = {"actors": [{"id": "hero", "x": 0.2}, {"id": "bot", "x": 0.8, "color": "red"}],
        "props": [{"kind": "table", "x": 0.5}, {"kind": "laptop", "x": 0.5}, {"kind": "unknown", "x": 0.1}],
        "acting": [{"who": "hero", "do": "walk", "from": 0, "to": 0.5, "x": 0.6, "emotion": "happy"},
                   {"who": "hero", "do": "cheer", "from": 0.5, "to": 1, "effect": "sparkle"},
                   {"who": "bot", "do": "chase", "from": 0, "to": 0.5, "x": 0.9},
                   {"who": "bot", "do": "talk", "from": 0.5, "to": 1, "prop": "phone"}],
        "camera": [{"from": 0.5, "to": 1, "zoom": 1.4, "on": "hero"}]}


@unittest.skipUnless(A.available(), "нет cairo")
class Drawing(unittest.TestCase):
    def test_frames_count_and_size(self):
        frames = list(A.render_frames(SPEC, "classic_light", (320, 180), 2.0))
        self.assertEqual(len(frames), 2 * A.FPS)
        self.assertEqual(len(frames[0]), 320 * 180 * 4)

    def test_something_is_drawn_and_changes(self):
        frames = list(A.render_frames(SPEC, "classic_light", (320, 180), 1.0))
        self.assertNotEqual(frames[0], frames[-1])                 # движется
        dark = sum(1 for i in range(0, len(frames[0]), 4) if frames[0][i] < 100)
        self.assertGreater(dark, 200)                              # на белом фоне есть чёрные линии человечков

    def test_every_style_and_action_renders(self):
        for style in A.LOOKS:
            list(A.render_frames(SPEC, style, (160, 90), 0.2))
        acting = [{"who": "hero", "do": d, "from": i / len(A.ACTIONS), "to": (i + 1) / len(A.ACTIONS)} for i, d in enumerate(A.ACTIONS)]
        list(A.render_frames({"acting": acting}, "neon_desktop", (160, 90), len(A.ACTIONS) * 0.2))

    def test_background_picture(self):
        from PIL import Image

        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        Image.new("RGB", (400, 300), (10, 120, 40)).save(d / "bg.png")
        frame = next(A.render_frames({}, "cozy", (160, 90), 0.1, background=d / "bg.png"))
        self.assertEqual(frame[:3], bytes([40, 120, 10]))           # угол кадра — цвет фона (BGRA)


class Logic(unittest.TestCase):
    def test_synonyms_and_unknown(self):
        s = A.Scene({"acting": [{"do": "chase", "from": 0, "to": 0.5}, {"do": "летать", "from": 0.5, "to": 1}]}, secs=2)
        self.assertEqual([x["do"] for x in s.segs["hero"]], ["run", "stand"])

    def test_walk_moves_and_turns(self):
        s = A.Scene({"actors": [{"id": "hero", "x": 0.7}], "acting": [{"do": "walk", "from": 0, "to": 0.5, "x": 0.2}]}, secs=4)
        self.assertAlmostEqual(s.where("hero", 0)[0], 0.7)
        self.assertAlmostEqual(s.where("hero", 3)[0], 0.2)
        self.assertEqual(s.where("hero", 1)[1], -1)                # идёт влево — смотрит влево

    def test_emotion_from_action_and_effects(self):
        s = A.Scene(SPEC, secs=4)
        _pose, emo, prop, effect, _talk = s.state("hero", 3.0)
        self.assertEqual((emo, effect), ("happy", "sparkle"))
        self.assertEqual(s.state("bot", 3.0)[2], "phone")

    def test_lying_figure_stays_on_the_ground(self):
        pts, _r = A.skeleton(A.pose_of("lie"), 100, 500, 200, 1)
        self.assertLessEqual(max(p[1] for k, p in pts.items() if k != "head"), 500.01)

    def test_camera_zooms_on_hero(self):
        s = A.Scene(SPEC, secs=4)
        self.assertEqual(s.cam(0.5)[0], 1.0)
        self.assertGreater(s.cam(3.5)[0], 1.3)


class Script(unittest.TestCase):
    def test_missing_moves_are_filled(self):
        script = {"scenes": [{"picture": "x", "narration": "Почему так?"}, {"picture": "y", "narration": "Ура, получилось!",
                                                                             "anim": {"acting": []}}]}
        sp.fill_anim(script)
        self.assertEqual(script["scenes"][0]["anim"]["acting"][-1]["do"], "think")
        self.assertEqual(script["scenes"][1]["anim"]["acting"][-1]["do"], "cheer")
        self.assertTrue(script["scenes"][0]["anim_auto"])

    def test_anim_prompt_ends_with_format(self):
        p = sp.prompt("стикмен", duration=30, anim=True)
        self.assertIn("ТОЛЬКО эти слова", p)
        self.assertTrue(p.rstrip().endswith('"camera": [...]}}]}'))

    def test_editor_keeps_moves(self):
        moves = {"acting": [{"who": "hero", "do": "jump", "from": 0, "to": 1}]}
        draft = json.dumps({"title": "t", "style_key": "classic_dark", "scenes": [
            {"picture": "a", "narration": "Раз.", "anim": moves, "place": "room"} for _ in range(4)]}, ensure_ascii=False)
        edited = json.dumps({"title": "t", "style_key": "classic_dark", "scenes": [
            {"picture": "a", "narration": "Раз, лучше."} for _ in range(4)]}, ensure_ascii=False)
        answers = iter([draft, edited])
        out = sp.write("стикмен", ask=lambda p: next(answers), search=lambda a: "", anim=True)
        self.assertEqual(out["scenes"][0]["narration"], "Раз, лучше.")
        self.assertEqual(out["scenes"][0]["anim"], moves)


class Studio(unittest.TestCase):
    def test_anim_is_free_except_world_backgrounds(self):
        scenes = [{"picture": "x", "narration": "а", "place": "cafe"}, {"picture": "y", "narration": "б", "place": "cafe"},
                  {"picture": "z", "narration": "в", "place": "street"}]
        self.assertEqual(studio.estimate(scenes, "anim", "neon_desktop"), 0)
        self.assertAlmostEqual(studio.estimate(scenes, "anim", "cozy"), 2 * studio.SLIDE_COST)

    def test_clean_scenes_keeps_moves(self):
        out = studio.clean_scenes([{"picture": "x", "narration": "y", "anim": {"acting": []}, "place": "room"}])
        self.assertEqual(out[0]["anim"], {"acting": []})
        self.assertEqual(out[0]["place"], "room")

    @unittest.skipUnless(A.available(), "нет cairo")
    def test_real_anim_clip(self):
        try:
            studio.ffmpeg()
        except studio.StudioError:
            self.skipTest("нет ffmpeg")
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        voice = d / "v.wav"
        studio.run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:duration=1.0", voice])
        out = A.anim_clip(SPEC, "classic_dark", voice, 1.5, (320, 180), d / "c.mp4", words=[(0, 0.5, "Привет")])
        self.assertAlmostEqual(studio.duration(out), 1.5, delta=0.15)


class Tool(unittest.TestCase):
    def setUp(self):
        from chloe import qwen_media as qm
        from chloe.tools import media

        self.media = media
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for target, name, val in ((qm, "VIDEO_DIR", self.dir / "vid"), (studio, "PROJECTS", self.dir / "vid" / "проекты"),
                                  (studio, "ffmpeg", lambda: "ffmpeg"), (media, "_say", lambda t: None),
                                  (media, "show", lambda p: None), (A, "available", lambda: True)):
            p = mock.patch.object(target, name, val)
            p.start()
            self.addCleanup(p.stop)
        media.jobs.clear()

    def test_cartoon_does_not_ask_about_money(self):
        script = {"title": "Мульт", "logline": "", "style_key": "neon_desktop", "characters": "",
                  "scenes": [{"picture": "x", "narration": "Фраза.", "anim": {"acting": []}} for _ in range(3)]}
        with mock.patch.object(sp, "write", return_value=script) as w, mock.patch.object(self.media, "confirm") as ask, \
                mock.patch.object(studio, "make_film", return_value=self.dir / "m.mp4") as film:
            out = self.media.tool_make_film({"idea": "стикмен", "mode": "anim", "style": "неон"})
            import time
            for _ in range(50):
                if self.media.jobs and list(self.media.jobs.values())[0]["state"] != "работаю":
                    break
                time.sleep(0.05)
        ask.assert_not_called()
        self.assertTrue(w.call_args.kwargs["anim"])
        self.assertEqual(film.call_args.kwargs["look"], "neon_desktop")
        self.assertIn("кредиты не тратятся", out)


if __name__ == "__main__":
    unittest.main()
