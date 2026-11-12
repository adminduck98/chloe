"""Физика тела: падение по законам физики — пол, края экрана, окна; потом встаёт; звуки на настоящих касаниях."""
import math
import unittest

from chloe import animator as A
from chloe import ragdoll as RG

W, H = 1280, 720


def standing(x=500, facing=-1):
    pose = dict(A.BASE)
    pose.update(A.pose_of("stand"))
    size = A.FIG * H
    pts, r = A.skeleton(pose, x, A.GROUND * H, size, facing)
    return pts, size


class Solver(unittest.TestCase):
    def test_flies_falls_and_rests_on_the_floor(self):
        pts, size = standing()
        sim = RG.simulate(pts, RG.push_for(size, 1, H), A.GROUND * H, W, H, size=size)
        self.assertLess(sim["rest"], 1.8)                                 # успокоился
        last = sim["frames"][-1][1]
        self.assertGreater(last["hip"][0], pts["hip"][0] + size * 0.3)    # отлетел вперёд по удару
        self.assertTrue(all(y <= A.GROUND * H + 1 for _t, fr in sim["frames"] for _x, y in fr.values()))   # не под полом
        self.assertTrue(any(kind == "floor" for _t, kind, _x, _f in sim["hits"]))

    def test_bones_keep_their_length(self):
        pts, size = standing()
        sim = RG.simulate(pts, RG.push_for(size, 1, H), A.GROUND * H, W, H, size=size)
        for a, b in (("hip", "kn1"), ("el1", "hand1"), ("neck", "head")):
            d0 = math.dist(pts[a], pts[b])
            for _t, fr in sim["frames"][::5]:
                self.assertAlmostEqual(math.dist(fr[a], fr[b]), d0, delta=d0 * 0.08)

    def test_window_and_screen_edge_stop_the_body(self):
        pts, size = standing(1150)
        sim = RG.simulate(pts, RG.push_for(size, 1, H, 1.5), A.GROUND * H, W, H, size=size)
        self.assertTrue(all(x <= W for _t, fr in sim["frames"] for x, _y in fr.values()))
        pts, size = standing(500)
        wall = (700, 250, 200, 250)
        sim = RG.simulate(pts, RG.push_for(size, 1, H), A.GROUND * H, W, H, [wall], size=size)
        self.assertTrue(any(kind == "window" for _t, kind, _x, _f in sim["hits"]))
        self.assertLess(sim["frames"][-1][1]["hip"][0], 700 + 200)        # сквозь окно не пролетел

    def test_sample_interpolates(self):
        pts, size = standing()
        sim = RG.simulate(pts, RG.push_for(size, 1, H), A.GROUND * H, W, H, size=size)
        a, b = RG.sample(sim, 0.2), RG.sample(sim, 0.21)
        self.assertLess(math.dist(a["hip"], b["hip"]), size * 0.2)


class InScene(unittest.TestCase):
    SPEC = {"actors": [{"id": "a", "x": 0.3}, {"id": "b", "x": 0.5, "facing": "left"}],
            "acting": [{"who": "a", "do": "punch", "from": 0.05, "to": 0.2, "target": "b"}]}

    def test_action_style_uses_physics(self):
        sc = A.Scene(self.SPEC, "action", (W, H), 8.0)
        big = next(k for k in sc.knocks if k["big"])
        self.assertIn("rag", big)
        rest = sc._rag[big["rag"]]["rest"]
        self.assertEqual(sc.knocked("b", big["t"] + 0.1)[0], "ragdoll")
        self.assertEqual(sc.knocked("b", big["t"] + rest + 0.2)[0], "rise_rag")
        self.assertIsNone(sc.knocked("b", big["t"] + rest + 1.0))
        lay = sc._rag[big["rag"]]["frames"][-1][1]["hip"][0] / W
        self.assertAlmostEqual(sc.where("b", big["t"] + rest + 2)[0], lay, delta=0.03)   # встал там, где лёг
        kinds = [e["kind"] for e in sc.sound_events() if e["t"] > big["t"]]
        self.assertIn("thud", kinds)                                      # звук касания пола
        _h, pts, _r = sc._actor(None, "b", big["t"] + 0.3, None, measure=True)
        self.assertNotAlmostEqual(pts["hip"][0], sc._raw_pts("b", big["t"])[0]["hip"][0], delta=5)

    def test_other_styles_keep_the_classic_knockback(self):
        sc = A.Scene(self.SPEC, "neon_desktop", (W, H), 8.0)
        self.assertFalse(any(k.get("rag") for k in sc.knocks))
        on = A.Scene(dict(self.SPEC, physics=True), "neon_desktop", (W, H), 8.0)
        self.assertTrue(any(k.get("rag") for k in on.knocks))             # включается и в любом стиле


if __name__ == "__main__":
    unittest.main()
