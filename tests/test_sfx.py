"""Звуки мультиков: каждый чистый, громче всего — на кадре действия, шаги и удары — по формулам движения, «слух» на ролике."""
import pathlib
import shutil
import tempfile
import unittest

import numpy as np

from chloe import animator as A
from chloe import sfx as S


def scene(acting, actors=None, secs=6.0):
    return A.Scene({"actors": actors or [{"id": "a", "x": 0.2}, {"id": "b", "x": 0.8}], "acting": acting}, "classic_light",
                   (320, 180), secs)


class Sounds(unittest.TestCase):
    def test_every_sound_is_clean(self):
        for kind in S.RECIPES:
            for seed in range(6):
                x, peak = S.make(kind, seed)
                self.assertEqual(S.check(x), [], (kind, seed))
                self.assertLess(peak, len(x) / S.SR)

    def test_repeats_are_never_identical(self):
        a, _ = S.make("step", 1)
        b, _ = S.make("step", 2)
        self.assertFalse(np.allclose(a[:min(len(a), len(b))], b[:min(len(a), len(b))]))

    def test_check_finds_real_problems(self):
        t = np.arange(4410)
        x = np.sin(t / 10.0) * 0.5
        x[:50] *= np.linspace(0, 1, 50)
        x[-50:] *= np.linspace(1, 0, 50)
        click = x.copy()
        click[2000], click[2001] = 0.9, -0.9
        self.assertTrue(any(p.startswith("clicks") for p in S.check(click)))
        self.assertTrue(any(p.startswith("edge") for p in S.check(np.sin(t / 10.0 + 1))))
        self.assertTrue(any(p.startswith("clipping") for p in S.check(np.clip(x * 3, -1, 1))))
        self.assertTrue(any(p.startswith("dc") for p in S.check(x * 0.5 + 0.2)))
        self.assertEqual(S.check(np.zeros(1000)), ["silent: звука нет"])
        self.assertEqual(S.check(x), [])


class Placement(unittest.TestCase):
    def test_hit_is_loudest_on_its_frame(self):
        track, placed = S.render([{"t": 1.0, "kind": "punch"}, {"t": 2.0, "kind": "thud"}], 3.0)
        hits = S.onsets(track)
        for t in (1.0, 2.0):
            near = min(hits, key=lambda h: abs(h - t))
            self.assertTrue(t - 0.045 <= near <= t + 0.02, (t, near))      # раньше — чуть-чуть можно, позже — нельзя
        self.assertEqual(S.sync_report(track, placed)["off"], [])

    def test_sync_report_notices_a_late_sound(self):
        track, placed = S.render([{"t": 1.0, "kind": "punch"}], 3.0)
        placed[0]["t"] = 1.3                                              # будто удар на кадре 1,3 с, а звук на 1,0
        self.assertEqual(len(S.sync_report(track, placed)["off"]), 1)

    def test_pan_follows_the_actor(self):
        track, _ = S.render([{"t": 0.5, "kind": "punch", "pan": -1}], 1.0, room=False)
        self.assertGreater(np.abs(track[:, 0]).max(), np.abs(track[:, 1]).max() * 1.5)

    def test_no_dead_silence_and_no_clipping(self):
        track, _ = S.render([{"t": 0.2 + 0.05 * i, "kind": "punch"} for i in range(20)], 2.0)
        self.assertLess(np.abs(track).max(), 1.0)
        self.assertGreater(np.abs(track[int(1.8 * S.SR):]).max(), 0)     # фон комнаты — не цифровой ноль


class Events(unittest.TestCase):
    def kinds(self, ev):
        return [e["kind"] for e in ev]

    def test_footsteps_follow_the_gait(self):
        sc = scene([{"who": "a", "do": "walk", "from": 0, "to": 0.5, "x": 0.6}])
        ev = sc.sound_events()
        steps = [e["t"] for e in ev if e["kind"] == "step"]
        gaps = [b - a for a, b in zip(steps, steps[1:])]
        self.assertGreaterEqual(len(steps), 4)
        self.assertLess(max(gaps) - min(gaps), 0.01)                       # шаги — ровным темпом походки
        self.assertTrue(0.3 < gaps[0] < 0.8)                               # живой темп: 1,3–3 шага в секунду
        pans = [e["pan"] for e in ev if e["kind"] == "step"]
        self.assertLess(pans[0], pans[-1])                                 # идёт вправо — звук тоже

    def test_punch_sounds_when_the_arm_is_out(self):
        sc = scene([{"who": "a", "do": "punch", "from": 0.5, "to": 0.7}])
        ev = sc.sound_events()
        t_hit = sc.hit_times()[0][0]
        hit = next(e for e in ev if e["kind"] == "punch")
        self.assertAlmostEqual(hit["t"], t_hit, places=3)
        pose, _ = A.action_pose("punch", t_hit - 3.0, 1.2)
        self.assertEqual(pose.get("_hit"), 1.0)                            # рука в этот момент вытянута
        self.assertLess(next(e for e in ev if e["kind"] == "swish")["t"], hit["t"])

    def test_fall_jump_throw_and_icons(self):
        ev = scene([{"who": "b", "do": "fall", "from": 0, "to": 0.5},
                    {"who": "a", "do": "jump", "from": 0, "to": 0.3, "effect": "bulb"},
                    {"who": "a", "do": "throw", "from": 0.5, "to": 0.8, "target": "b", "prop": "ball"}]).sound_events()
        self.assertIn(3.0 * 0.625, [e["t"] for e in ev if e["kind"] == "thud"])
        self.assertIn("ding", self.kinds(ev))
        self.assertIn("swish", self.kinds(ev))
        self.assertEqual(ev[-1]["kind"], "pop")                            # мяч пойман — последним
        self.assertTrue(all(0 <= e["t"] <= 6.0 for e in ev))

    def test_scene_track_file(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        spec = {"actors": [{"id": "a"}], "acting": [{"who": "a", "do": "kick", "from": 0, "to": 1}]}
        path = A.scene_sounds(spec, "classic_light", (320, 180), 2.0, d / "clip00.part.mp4", transition=True)
        self.assertEqual(pathlib.Path(path).name, "clip00.sfx.wav")
        x, sr = S.load_wav(path)
        self.assertAlmostEqual(len(x) / sr, 2.0, delta=0.01)
        self.assertIsNone(A.scene_sounds(dict(spec, sounds=False), "classic_light", (320, 180), 2.0, d / "c.mp4"))


class Turn(unittest.TestCase):
    def test_silence_before_the_biggest_hit(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        spec = {"actors": [{"id": "a"}], "acting": [{"who": "a", "do": "walk", "from": 0, "to": 0.5, "x": 0.7},
                                                    {"who": "a", "do": "fall", "from": 0.5, "to": 1}]}
        plain, _ = S.load_wav(A.scene_sounds(spec, "classic_light", (320, 180), 4.0, d / "a.mp4"))
        turn, _ = S.load_wav(A.scene_sounds(dict(spec, beat="turn"), "classic_light", (320, 180), 4.0, d / "b.mp4"))
        hit = 2.0 + 2.0 * 0.625
        before = slice(int((hit - 0.5) * S.SR), int((hit - 0.1) * S.SR))
        self.assertLess(np.abs(turn[before]).max(), np.abs(plain[before]).max() * 0.5)     # перед ударом стихло
        self.assertGreater(np.abs(turn[before]).max(), 0)                                  # но не цифровой ноль
        at = slice(int((hit - 0.02) * S.SR), int((hit + 0.05) * S.SR))
        self.assertGreater(np.abs(turn[at]).max(), np.abs(plain[at]).max())               # а удар — громче


class Hearing(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def wav(self, x):
        return S.save_wav(self.dir / "a.wav", x)

    def test_hears_a_dropout(self):
        t = np.arange(6 * S.SR) / S.SR
        x = 0.2 * np.sin(2 * np.pi * 220 * t)
        self.assertEqual(S.listen(self.wav(x))["notes"], [])
        x[2 * S.SR:3 * S.SR] = 0                                             # секунда цифровой тишины посреди ролика
        report = S.listen(self.wav(x))
        self.assertFalse(report["ok"])
        self.assertIn("звук пропадает", report["notes"][0])

    def test_hears_a_scene_much_louder_than_others(self):
        t = np.arange(8 * S.SR) / S.SR
        x = 0.1 * np.sin(2 * np.pi * 220 * t)
        x[4 * S.SR:6 * S.SR] *= 3                                            # третья сцена из четырёх — на 9,5 дБ громче
        report = S.listen(self.wav(x), [2, 2, 2, 2])
        self.assertIn("3 (+", " ".join(report["notes"]))

    def test_hears_overload(self):
        t = np.arange(3 * S.SR) / S.SR
        report = S.listen(self.wav(np.clip(1.5 * np.sin(2 * np.pi * 220 * t), -1, 1)))
        self.assertTrue(any("перегруз" in n for n in report["notes"]))


if __name__ == "__main__":
    unittest.main()
