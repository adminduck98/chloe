"""Воксельный 3D-уровень: план (прыжки, монеты, блок) и сборка ролика поверх кадров Blender."""
import os
import unittest
from unittest import mock

from chloe import level_plan as LP
from chloe import voxel_level as VL


class Plan(unittest.TestCase):
    def setUp(self):
        self.p = LP.Plan()

    def test_jumps_cover_spikes_and_gaps(self):
        for col, kind, n in self.p.features:
            if kind not in ("spikes", "gap"):
                continue
            x = col
            while x < col + n:
                t = LP.WAIT + (x - LP.START) / LP.SPEED
                _, lift, air, _ = self.p.hero(t)
                self.assertTrue(air and lift > 0.3, "{} на x={:.2f}".format(kind, x))
                x += 0.1

    def test_head_touches_block_not_through(self):
        col = self.p.block[0][0]
        top = max(self.p.hero(LP.WAIT + (x / 10 - LP.START) / LP.SPEED)[1] for x in range((col - 2) * 10, (col + 3) * 10))
        self.assertAlmostEqual(top + LP.HERO_H, self.p.block_z, delta=0.06)

    def test_events_all_coins_and_one_block_hit(self):
        ev = self.p.events(15, self.p.portal_t + 1)
        self.assertEqual(len(ev[-1]["taken"]), len(self.p.coins))               # все монеты собраны
        self.assertIsNotNone(ev[-1]["block_hit"])
        self.assertEqual(ev[-1]["score"], 10 * len(self.p.coins) + 100)
        self.assertEqual(sum(1 for e in ev for k, _ in e["new"] if k == "block"), 1)

    def test_camera_smooth(self):
        xs = [LP.smooth_cam(self.p, f / 15) for f in range(int(self.p.portal_t * 15))]
        self.assertLess(max(abs(b - a) for a, b in zip(xs, xs[1:])), 0.6)       # без рывков между кадрами


class Assemble(unittest.TestCase):
    def test_overlay_size_and_final_title(self):
        from PIL import Image

        p = LP.Plan()
        ev = p.events(15, p.portal_t + 2)
        img = Image.new("RGB", (VL.OUT_W, VL.OUT_H), (120, 160, 230))
        f_end = int((p.portal_t + 1.5) * 15)
        a = VL.overlay(img, ev[10], 10, 15, p)
        b = VL.overlay(img, ev[f_end], f_end, 15, p)
        self.assertEqual(a.size, (1080, 1920))
        self.assertNotEqual(a.getpixel((540, 600)), b.getpixel((540, 600)))   # в конце — надпись «Уровень пройден!»

    def test_no_blender_clear_message(self):
        with mock.patch.dict(os.environ, {"CHLOE_BPY_PYTHON": ""}), mock.patch("shutil.which", return_value=None):
            with self.assertRaises(VL.LevelError) as e:
                VL.blender_cmd()
        self.assertIn("Blender", str(e.exception))


if __name__ == "__main__":
    unittest.main()
