"""Своя хореография с видео: точки тела → движение стикмена, пропуски, личная библиотека, инструмент learn_move.
MediaPipe здесь не нужен — точки тела искусственные (человек идёт вправо и бьёт рукой)."""
import json
import math
import unittest
from unittest import mock

import numpy as np

from chloe import animator as A
from chloe import mocap as MC
from chloe import video_mocap as VM


def walker(n=50, fps=25, punch_at=30):
    """33 точки MediaPipe на кадр: человек идёт вправо, на кадре punch_at правая рука вытянута вперёд."""
    pts = np.zeros((n, 33, 3))
    pts[:, :, 2] = 0.99
    for i in range(n):
        x0, ph = 200 + i * 3, math.sin(i / fps * 2 * math.pi * 1.8)
        hip_y, sh_y, head_y = 300, 200, 150
        set_ = lambda j, x, y: pts[i, j, :2].__setitem__(slice(None), (x, y))   # noqa: E731
        for j, dx in ((23, -5), (24, 5)):
            set_(j, x0 + dx, hip_y)
        for j in (11, 12):
            set_(j, x0, sh_y)
        for j in (7, 8):
            set_(j, x0 + 4, head_y)
        set_(0, x0 + 14, head_y + 3)                                    # нос — смотрит вправо
        set_(26, x0 + 30 * ph, 350)
        set_(28, x0 + 45 * ph, 400)
        set_(25, x0 - 30 * ph, 350)
        set_(27, x0 - 45 * ph, 400)
        reach = 1.0 if abs(i - punch_at) <= 1 else 0.2
        set_(14, x0 + 50 * reach, 210)
        set_(16, x0 + 100 * reach, 215)
        set_(13, x0 - 10, 240)
        set_(15, x0 - 5, 280)
    return pts


class FromPoints(unittest.TestCase):
    def test_walk_becomes_angles_and_steps(self):
        move = VM.to_move(walker())
        self.assertEqual(len(move["poses"]), 50)
        self.assertGreater(move["fwd"][-1], 0.3)                         # прошёл вправо
        hips = [p["hip1"] for p in move["poses"]]
        self.assertGreater(max(hips) - min(hips), 30)                    # ноги шагают
        self.assertTrue(any(abs(h - 30 / 25) < 0.1 for h in move["hits"]))   # удар рукой найден
        self.assertTrue(all(abs(p["torso"]) < 20 for p in move["poses"]))   # стоит прямо

    def test_mirror_for_people_facing_left(self):
        right, left = VM.to_move(walker()), VM.to_move(walker(), mirror=True)
        self.assertAlmostEqual(left["fwd"][-1], -right["fwd"][-1], places=3)

    def test_facing_left_is_found_by_itself(self):
        pts = walker()
        pts[:, :, 0] = 1000 - pts[:, :, 0]                               # то же видео, отражённое: идёт и смотрит влево
        self.assertTrue(VM.faces_left(pts))
        self.assertFalse(VM.faces_left(walker()))
        left = VM.to_move(pts)
        self.assertGreater(left["fwd"][-1], 0.3)                         # всё равно «вперёд» — вправо

    def test_hidden_far_arm_still_has_points(self):
        pts = walker()
        pts[:, 15, 2] = 0.1                                              # дальняя кисть всё время за телом
        pts[3, 15] = np.nan
        out = VM.fill_gaps(pts)
        self.assertFalse(np.isnan(out[:, :, :2]).any())
        move = VM.to_move(VM.smooth(out))
        self.assertTrue(all(np.isfinite(v) for p in move["poses"] for v in p.values()))

    def test_stickman_hands_and_feet_land_where_the_persons_are(self):
        pts = walker()
        for i in range(len(pts)):                                        # широкая стойка, плечи и бёдра разнесены (вполоборота)
            x0 = pts[i, 23, 0] + 5
            pts[i, 11, 0], pts[i, 12, 0] = x0 - 25, x0 + 25
            pts[i, 23, 0], pts[i, 24, 0] = x0 - 15, x0 + 15
            pts[i, 27, :2], pts[i, 28, :2] = (x0 - 60, 400), (x0 + 60, 400)
            pts[i, 25, :2], pts[i, 26, :2] = (x0 - 35, 350), (x0 + 35, 350)
        move = VM.to_move(pts)
        P = {k: (VM.LM[k], ) for k in VM.LM}
        leg_px = np.hypot(35 - 15, 50) + np.hypot(25, 50)
        size = (A.SEG["thigh"] + A.SEG["shin"]) / leg_px                 # пикселей видео → доли роста стикмена
        i = 25
        pose = move["poses"][i]
        sk, _r = A.skeleton(pose, 0.0, 0.0, 1.0, 1)
        hip = sk["hip"]
        hx = (pts[i, 23, 0] + pts[i, 24, 0]) / 2
        hy = (pts[i, 23, 1] + pts[i, 24, 1]) / 2
        for key, j in (("foot1", 28), ("foot2", 27)):
            want = ((pts[i, j, 0] - hx) * size, (pts[i, j, 1] - hy) * size)
            got = (sk[key][0] - hip[0], sk[key][1] - hip[1])
            self.assertLess(math.dist(want, got), 0.03, key)             # стопа стикмена — там же, где у человека
        self.assertGreater(abs(sk["foot1"][0] - sk["foot2"][0]), 0.2)     # стойка широкая
        del P

    def test_body_as_filmed_is_played_by_the_animator(self):
        pts = walker()
        pts[:, 12, 0] += 30                                              # плечи разнесены (снято вполоборота)
        pts[:, 11, 0] -= 30
        move = VM.to_move(pts)
        self.assertEqual(len(move["body"]), len(move["poses"]))
        fr = move["body"][25]
        self.assertGreater(fr["sh1"][0] - fr["sh2"][0], 0.05)            # два плеча, правое — впереди
        with mock.patch.object(MC, "library", return_value={"my_move": dict(move, fps=25, loop=False)}), \
                mock.patch.object(MC, "rate_for", return_value=1.0):
            sc = A.Scene({"actors": [{"id": "a", "x": 0.5}], "acting": [{"who": "a", "do": "my_move", "from": 0, "to": 1}]},
                         "action3d", (640, 360), 2.0)
            pts_ = sc._as_filmed("a", 1.0, A.skeleton(A.pose_of("stand"), 320, sc.ground, 100, 1)[0], 100, 1)
        self.assertIn("sh1", pts_)
        self.assertGreater(pts_["sh1"][0] - pts_["sh2"][0], 4)           # у героя тоже два плеча, как у человека

    def test_3d_body_turns_with_the_camera(self):
        n = 30
        w3 = np.zeros((n, 33, 3))                                        # человек стоит лицом к камере, руки вперёд
        for i in range(n):
            for j, (x, y, z) in {23: (0.1, 0, 0), 24: (-0.1, 0, 0), 25: (0.1, 0.42, 0), 26: (-0.1, 0.42, 0),
                                 27: (0.1, 0.85, 0), 28: (-0.1, 0.85, 0), 11: (0.18, -0.5, 0), 12: (-0.18, -0.5, 0),
                                 13: (0.2, -0.45, -0.25), 14: (-0.2, -0.45, -0.25), 15: (0.12, -0.45, -0.5),
                                 16: (-0.12, -0.45, -0.5), 0: (0, -0.62, -0.12), 7: (0.07, -0.62, 0), 8: (-0.07, -0.62, 0)}.items():
                w3[i, j] = (x, y, z)
        frames, face = VM.body3d(VM.smooth3d(w3))
        self.assertAlmostEqual(face, -90, delta=5)                        # смотрит на камеру
        move = dict(VM.to_move(walker(n)), body3d=frames, face3d=face, fps=25, loop=False)
        got = {}
        for ang in ("filmed", "side"):
            with mock.patch.object(MC, "library", return_value={"m": move}), mock.patch.object(MC, "rate_for", return_value=1.0):
                sc = A.Scene({"actors": [{"id": "a", "x": 0.5, "angle": ang}], "acting": [{"who": "a", "do": "m", "from": 0, "to": 1}]},
                             "action3d", (640, 360), 1.2)
                got[ang] = sc._as_filmed("a", 0.6, A.skeleton(A.pose_of("stand"), 320, sc.ground, 100, 1)[0], 100, 1)
        f, s_ = got["filmed"], got["side"]
        self.assertGreater(abs(f["sh1"][0] - f["sh2"][0]), 10)            # анфас — плечи широко
        self.assertLess(abs(s_["sh1"][0] - s_["sh2"][0]), 3)              # сбоку — плечи друг за другом
        self.assertGreater(s_["hand1"][0] - s_["hp1"][0], 20)             # а руки — вперёд, по направлению взгляда

    def test_held_arm_is_not_a_strike(self):
        pts = walker(n=60, punch_at=200)                                 # без удара
        for i in range(20, 60):                                          # с 20-го кадра правая рука вытянута и держится
            x0 = pts[i, 23, 0] + 5
            pts[i, 14, :2] = (x0 + 50, 210)
            pts[i, 16, :2] = (x0 + 100, 215)
        self.assertEqual(VM.to_move(pts)["hits"], [])
        self.assertTrue(VM.to_move(walker())["hits"])                    # а выброс с возвратом — удар

    def test_gaps_are_filled(self):
        pts = walker()
        pts[10:14] = np.nan                                              # человек на миг пропал
        pts[20, 16, 2] = 0.05                                            # кисть не видна
        out = VM.fill_gaps(pts)
        self.assertFalse(np.isnan(out[:, :, :2]).any())
        self.assertTrue(pts[9, 23, 0] <= out[11, 23, 0] <= pts[14 if not np.isnan(pts[14, 23, 0]) else 15, 23, 0])

    def test_nobody_on_video(self):
        pts = np.full((20, 33, 3), np.nan)
        with self.assertRaises(VM.VideoMocapError):
            VM.fill_gaps(pts)


class Library(unittest.TestCase):
    def setUp(self):
        self.addCleanup(MC.reload)
        p = VM.user_path()
        self.addCleanup(lambda: p.unlink(missing_ok=True))

    def test_saved_move_is_usable_in_scenes(self):
        key = VM.save("Мой Удар!", VM.to_move(walker()))
        self.assertEqual(key, "moy_udar")                                # по-русски — латиницей
        key = VM.save("my_kick", VM.to_move(walker()))
        self.assertIn("my_kick", MC.library())
        sc = A.Scene({"actors": [{"id": "a", "x": 0.3}], "acting": [{"who": "a", "do": "my_kick", "from": 0, "to": 1}]},
                     "action", (640, 360), 2.0)
        self.assertEqual(sc.segs["a"][0]["do"], "my_kick")
        self.assertIsNotNone(MC.cartoon("my_kick"))                       # и с мультяшным фильтром

    def test_tool(self):
        from chloe.tools import media

        self.assertIn("нет", media.tool_learn_move({"action": "list"}).lower())
        self.assertIn("Нужно видео", media.tool_learn_move({"path": "/нет/такого.mp4"}))
        with mock.patch.object(VM, "learn", return_value=("my_move", 2.0, (48, 50))):
            out = media.tool_learn_move({"path": __file__, "name": "my_move"})
        self.assertIn("my_move", out)
        self.assertIn("48 кадрах из 50", out)


if __name__ == "__main__":
    unittest.main()
