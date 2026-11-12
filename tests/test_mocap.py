"""Живые движения (захват движения CMU): чтение BVH, прямая кинематика, перенос на 2D-стикмена, библиотека и её
подключение к мультипликатору (темп шага, повтор ударов, моменты ударов и приземлений, сдвиг тела)."""
import unittest

import numpy as np

from chloe import animator as A
from chloe import mocap as M

BVH = """HIERARCHY
ROOT Hips
{
  OFFSET 0 0 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
  JOINT Spine
  {
    OFFSET 0 10 0
    CHANNELS 3 Zrotation Yrotation Xrotation
    End Site
    {
      OFFSET 0 5 0
    }
  }
}
MOTION
Frames: 2
Frame Time: 0.1
0 20 0 0 0 0 0 0 0
5 20 0 90 0 0 0 0 0
"""


class Bvh(unittest.TestCase):
    def test_parse_and_forward_kinematics(self):
        joints, frames, dt = M.parse_bvh(BVH)
        self.assertEqual([j["name"] for j in joints if not j.get("end")], ["Hips", "Spine"])
        self.assertEqual(frames.shape, (2, 9))
        self.assertAlmostEqual(dt, 0.1)
        pos = M.positions(joints, frames)
        np.testing.assert_allclose(pos["Spine"][0], [0, 30, 0], atol=1e-6)     # стоит прямо
        np.testing.assert_allclose(pos["Spine"][1], [5 - 10, 20, 0], atol=1e-6)  # корпус повернули на 90° вокруг Z

    def test_rel_angles_have_no_jumps(self):
        a = M._rel(np.array([170.0, 179.0, -179.0, -170.0]))
        self.assertTrue(np.all(np.abs(np.diff(a)) < 20))


class Library(unittest.TestCase):
    def test_library_is_shipped_with_credit(self):
        import json

        data = json.loads(M.DATA.read_text(encoding="utf-8"))
        self.assertIn("Carnegie Mellon", data["credit"])
        for name in ("walk", "run", "punch", "kick", "backflip", "cartwheel", "jumpkick", "slip"):
            self.assertIn(name, M.library())

    def test_standing_frames_look_upright(self):
        walk = M.library()["walk"]["poses"]
        self.assertTrue(all(abs(p["torso"]) < 25 for p in walk))         # идёт прямо, не падает
        self.assertGreater(max(p["hip1"] for p in walk) - min(p["hip1"] for p in walk), 30)   # ноги правда шагают

    def test_walk_speed_follows_the_path(self):
        slow, fast = M.rate_for("walk", 3, 0.4), M.rate_for("walk", 3, 1.0)
        self.assertLess(slow, fast)
        self.assertEqual(M.rate_for("walk", 3, 100), 1.8)                  # не быстрее разумного

    def test_punch_repeats_in_long_segments(self):
        one = M.duration("punch")
        self.assertEqual(M.reps("punch", one), 1)
        self.assertEqual(M.reps("punch", one * 3), 3)
        self.assertEqual(len(M.hits_in("punch", one * 3)), 3)
        self.assertEqual(M.reps("backflip", 30), 1)                        # сальто — один раз

    def test_pose_at_interpolates(self):
        pose, fwd = M.pose_at("walk", 0.02, 2.0)
        self.assertIn("hip1", pose)
        self.assertIsNone(M.pose_at("nothing", 0, 1))


class Animator(unittest.TestCase):
    def scene(self, acting, actors=None):
        return A.Scene({"actors": actors or [{"id": "a", "x": 0.3}, {"id": "b", "x": 0.7, "facing": "left"}],
                        "acting": acting}, "classic_light", (640, 360), 8.0)

    def test_moves_are_actions_with_synonyms(self):
        for name in A.MOCAP_MOVES:
            self.assertIn(name, A.ACTIONS)
        sc = self.scene([{"who": "a", "do": "somersault", "from": 0, "to": 0.4}])
        self.assertEqual(sc.segs["a"][0]["do"], "backflip")

    def test_hit_marker_on_the_recorded_hit(self):
        t = M.hits_in("kick", 1.5)[0]
        self.assertEqual(A.action_pose("kick", t, 1.5)[0].get("_hit"), 1.0)
        self.assertIsNone(A.action_pose("kick", 0.0, 1.5)[0].get("_hit"))

    def test_flying_kick_reaches_and_knocks_the_target(self):
        sc = self.scene([{"who": "a", "do": "jumpkick", "from": 0.1, "to": 0.6, "target": "b"}])
        self.assertTrue(sc.knocks and sc.knocks[-1]["who"] == "b")
        self.assertTrue(any(e["kind"] == "punch" for e in sc.sound_events()))

    def test_acrobatics_moves_the_body_and_lands_with_sound(self):
        sc = self.scene([{"who": "a", "do": "slip", "from": 0.1, "to": 0.9}])
        self.assertNotAlmostEqual(sc.where("a", 7.9)[0], 0.3, places=2)    # поскользнулся — проехал
        self.assertTrue(any(e["kind"] == "thud" for e in sc.sound_events()))

    def test_nobody_goes_under_the_floor(self):
        import cairo

        sc = self.scene([{"who": "a", "do": "backflip", "from": 0.0, "to": 0.5}])
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 640, 360)
        for i in range(0, 100, 4):
            _h, pts, r = sc._actor(cairo.Context(surf), "a", i / 25, (0, 0, 0))
            self.assertLessEqual(max(y for _x, y in pts.values()), sc.ground + 360 * 0.01 + 1)


class Dodges(unittest.TestCase):
    def scene(self, acting, **extra):
        spec = {"actors": [{"id": "a", "x": 0.3}, {"id": "b", "x": 0.5, "facing": "left"}], "acting": acting}
        spec.update(extra)
        return A.Scene(spec, "neon_desktop", (640, 360), 8.0)

    def test_new_moves_exist(self):
        for name in ("duck", "slide", "climb", "roll", "breakdance", "kazachok", "moonwalk", "ballet"):
            self.assertIn(name, M.library())
        self.assertEqual(self.scene([{"who": "a", "do": "dodge", "from": 0, "to": 0.3}]).segs["a"][0]["do"], "duck")

    def test_duck_makes_the_punch_miss(self):
        hit = [{"who": "b", "do": "punch", "from": 0.2, "to": 0.4, "target": "a"}]
        self.assertTrue(self.scene(hit).knocks)                                   # стоит — получает
        ducked = self.scene(hit + [{"who": "a", "do": "duck", "from": 0.15, "to": 0.45}])
        self.assertEqual(ducked.knocks, [])                                       # пригнулся — мимо

    def test_cursor_hit_misses_a_rolling_hero(self):
        cur = [{"t": 0.0, "x": 0.9, "y": 0.1}, {"t": 0.3, "hit": "a"}]
        self.assertTrue(self.scene([], cursor=cur).knocks)
        self.assertEqual(self.scene([{"who": "a", "do": "roll", "from": 0.25, "to": 0.6}], cursor=cur).knocks, [])

    def test_low_hero_has_a_low_target_box(self):
        sc = self.scene([{"who": "a", "do": "duck", "from": 0.0, "to": 0.5}])
        box = next(b for b in sc._boxes(2.0) if b[0] == "a")
        self.assertGreater(box[3], sc.ground - sc.fig * 0.5)                      # пригнулся — иконка пролетит над ним


if __name__ == "__main__":
    unittest.main()
