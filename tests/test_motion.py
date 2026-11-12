"""Плавность движения: разгон и торможение, замах — удар — отдача, суставы с инерцией, приземление с приседом."""
import unittest

from chloe import animator as A


class Motion(unittest.TestCase):
    def test_ramp_speeds_up_and_slows_down(self):
        self.assertEqual((A.ramp(0), A.ramp(1)), (0, 1))
        self.assertLess(A.ramp(0.1), 0.1)                                  # в начале медленнее равномерного
        self.assertGreater(A.ramp(0.9), 0.9)                               # в конце — уже почти на месте
        xs = [A.ramp(i / 100) for i in range(101)]
        self.assertTrue(all(b >= a for a, b in zip(xs, xs[1:])))

    def test_punch_winds_up_strikes_and_recoils(self):
        rate, peak = A.STRIKE["punch"]
        arm = {f: A.action_pose("punch", f / rate, 1.0)[0] for f in (0.0, peak - 0.08, peak, 0.4, 0.7)}
        self.assertLess(arm[peak - 0.08]["sh1"], arm[0.0]["sh1"] - 40)      # замах: рука ушла назад
        self.assertGreater(arm[peak]["sh1"], 90)                            # удар: рука прямая вперёд
        self.assertLess(abs(arm[peak]["el1"]), 5)
        self.assertEqual(arm[peak]["_hit"], 1.0)
        self.assertEqual(arm[peak - 0.08]["_hit"], 0.0)
        self.assertEqual(arm[0.7]["sh1"], arm[0.0]["sh1"])                  # вернулся в стойку
        kick = A.action_pose("kick", A.STRIKE["kick"][1] / A.STRIKE["kick"][0], 1.0)[0]
        self.assertGreater(kick["hip1"], 90)
        self.assertEqual(kick["_hit"], 1.0)

    def test_joints_follow_with_inertia(self):
        sc = A.Scene({"actors": [{"id": "a"}], "acting": [{"who": "a", "do": "cheer", "from": 0.5, "to": 1}]}, "classic_light",
                     (320, 180), 4.0)
        target = A.pose_of("cheer")["sh1"]
        seen = [sc._smooth("a", i / A.FPS, sc.state("a", i / A.FPS)[0])["sh1"] for i in range(int(4 * A.FPS))]
        start = int(2.0 * A.FPS)
        self.assertLess(seen[start + 1], sc.state("a", (start + 1) / A.FPS)[0]["sh1"])   # чуть отстаёт
        self.assertGreater(max(seen), target + 0.5)                          # и чуть проскакивает (довод)
        last = (len(seen) - 1) / A.FPS
        self.assertAlmostEqual(seen[-1], sc.state("a", last)[0]["sh1"], delta=1.0)   # а потом встаёт точно (с дыханием)
        again = sc._smooth("a", 3.0, sc.state("a", 3.0)[0])["sh1"]
        self.assertEqual(again, seen[int(3.0 * A.FPS)])                      # прошлый кадр — из памяти, для следа

    def test_landing_after_a_drop(self):
        sc = A.Scene({"actors": [{"id": "a", "x": 0.3}],
                      "cursor": [{"t": 0.1, "x": 0.3, "y": 0.35, "grab": "a"}, {"t": 0.3, "x": 0.6, "y": 0.1, "release": True}]},
                     "neon_desktop", (320, 180), 4.0)
        self.assertIsNone(sc.landed("a", 1.1))
        t = next(i / 100 for i in range(120, 400) if sc.landed("a", i / 100) is not None)
        self.assertLess(t, 2.0)
        self.assertIsNone(sc.landed("a", t + 1.2))


class Knockback(unittest.TestCase):
    SPEC = {"actors": [{"id": "a", "x": 0.2}, {"id": "b", "x": 0.7, "facing": "left"}],
            "acting": [{"who": "a", "do": "punch", "from": 0.2, "to": 0.45, "target": "b"}]}

    def scene(self):
        return A.Scene(self.SPEC, "neon_desktop", (640, 360), 8.0)

    def test_attacker_steps_in_to_reach(self):
        sc = self.scene()
        t0 = 0.2 * 8.0
        self.assertAlmostEqual(sc.where("a", t0)[0], 0.2, places=2)
        gap = sc.where("b", t0 + 0.35)[0] - sc.where("a", t0 + 0.35)[0]
        self.assertAlmostEqual(gap, A.REACH * 360 / 640, places=2)         # встал на длину удара

    def test_flinch_then_last_hit_knocks_back(self):
        sc = self.scene()
        kn = sc.knocks
        self.assertEqual(len(kn), 3)                                       # три удара за 2 с при 1,6 в секунду
        self.assertEqual([k["big"] for k in kn], [False, False, True])
        self.assertEqual(sc.knocked("b", kn[0]["t"] + 0.1)[0], "flinch")
        t = kn[-1]["t"]
        self.assertEqual(sc.knocked("b", t + 0.1)[0], "fly")
        self.assertEqual(sc.knocked("b", t + 0.6)[0], "slide")
        self.assertEqual(sc.knocked("b", t + 1.2)[0], "rise")
        self.assertIsNone(sc.knocked("b", t + 1.6))
        before, after = sc.where("b", t)[0], sc.where("b", t + 2.0)[0]
        self.assertAlmostEqual(after - before, 0.2, places=2)              # отлетел от обидчика вправо
        self.assertEqual(sc.where("b", t + 2.0)[1], -1)                    # и смотрит на него

    def test_knockback_sounds(self):
        sc = self.scene()
        t = sc.knocks[-1]["t"]
        ev = sc.sound_events()
        self.assertTrue(any(e["kind"] == "thud" and abs(e["t"] - (t + A.KNOCK_TIME * A.KNOCK_FLY)) < 0.01 for e in ev))
        self.assertGreaterEqual(sum(1 for e in ev if e["kind"] == "flutter"), 4)


if __name__ == "__main__":
    unittest.main()
