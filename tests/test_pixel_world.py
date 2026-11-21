"""Пиксельный мир: кадр рисуется, герой проходит уровень — прыгает над шипами и ямой, бьёт блок, собирает монеты."""
import unittest

import numpy as np

from chloe import pixel_world as PW


class PixelWorld(unittest.TestCase):
    def test_frame_size_and_pixels(self):
        d = PW.Demo()
        f = d.frame(2.0)
        self.assertEqual(f.shape, (384, 216, 3))
        self.assertEqual(f.dtype, np.uint8)
        big = PW.upscale(f)
        self.assertEqual(big.shape, (1920, 1080, 3))                      # ровно 1080×1920 для Shorts
        self.assertTrue((big[0:5, 0:5] == big[0, 0]).all())               # пиксель — квадрат 5×5

    def test_jumps_cover_obstacles(self):
        d = PW.Demo()
        for col, kind, n in d.features:
            if kind not in ("spikes", "gap"):
                continue
            for x in np.arange(col * PW.TILE, (col + n) * PW.TILE, 2.0):  # над каждым пикселем препятствия — в воздухе
                t = 0.8 + (x - d.start_x) / d.speed
                _, lift, air, _, _ = d.hero_at(t)
                self.assertTrue(air and lift > 4, "{} на x={}".format(kind, x))

    def test_runs_whole_level(self):
        d = PW.Demo(w=108, h=192)                                           # маленький кадр — быстро
        end = d.hero_at(0)[4] + 1.0
        t, block_hit = 0.0, False
        block_col = next(c for c, k, _ in d.features if k == "block")
        while t < end:
            x, lift, _, _, _ = d.hero_at(t)
            head = d.ground - lift - PW.HERO["height"] * 1.02
            if abs(x - (block_col * PW.TILE + 8)) < 12:                       # под блоком — сквозь него не пролетает
                self.assertGreaterEqual(head, (PW.GROUND_ROW - 5) * PW.TILE - 3)
            d.frame(t)
            block_hit = block_hit or bool(d.level.bumped)
            t += 1 / 15
        self.assertTrue(block_hit)
        self.assertGreaterEqual(d.coins, 8)
        self.assertGreater(d.score, 100)

    def test_hero_any_animator_move(self):
        from chloe import animator as A

        L = PW.Layer(96, 96)
        for move in ("walk", "run", "jump", "wave", "punch", "fall"):
            pose, _ = A.action_pose(move, 0.3, 1.0)
            pts = PW.draw_hero(L, dict(A.BASE, **pose), 48, 90, 1, "happy", 0.3)
            self.assertIn("head", pts)
        self.assertGreater(L.a.sum(), 200)


if __name__ == "__main__":
    unittest.main()
