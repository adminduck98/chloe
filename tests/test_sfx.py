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
        ev = scene([{"who": "a", "do": "walk", "from": 0, "to": 0.5, "x": 0.6}]).sound_events()
        steps = [e["t"] for e in ev if e["kind"] == "step"]
        self.assertEqual(len(steps), 14)                                   # 3 с ходьбы, 2,4 шага-цикла в секунду
        self.assertAlmostEqual(steps[1] - steps[0], 1 / 4.8, places=3)
        self.assertLess(steps[0] and ev[0]["pan"], steps[-1] and ev[-1]["pan"])   # идёт вправо — звук тоже

    def test_punch_sounds_when_the_arm_is_out(self):
        ev = scene([{"who": "a", "do": "punch", "from": 0.5, "to": 0.7}]).sound_events()
        hit = next(e for e in ev if e["kind"] == "punch")
        self.assertAlmostEqual(hit["t"], 3.0 + 0.175 / 1.6, places=3)
        pose, _ = A.action_pose("punch", hit["t"] - 3.0, 1.2)
        self.assertGreater(pose["_hit"], 0.99)                             # рука в этот момент дальше всего
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

    def test_hears_overload(self):
        t = np.arange(3 * S.SR) / S.SR
        report = S.listen(self.wav(np.clip(1.5 * np.sin(2 * np.pi * 220 * t), -1, 1)))
        self.assertTrue(any("перегруз" in n for n in report["notes"]))


if __name__ == "__main__":
    unittest.main()
