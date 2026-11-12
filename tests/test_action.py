"""Рисовка «Экшен»: толстые обведённые фигуры, растяжки, искры, кадр-негатив, пауза на ударе, камера следит за дракой."""
import unittest

from chloe import animator as A
from chloe import stickman_styles as ST

W, H = 640, 360
FIGHT = {"actors": [{"id": "a", "x": 0.3}, {"id": "b", "x": 0.6, "facing": "left", "color": "red"}],
         "acting": [{"who": "a", "do": "punch", "from": 0.1, "to": 0.3, "target": "b"}]}


def scene(spec=FIGHT, style="action", secs=8.0):
    return A.Scene(spec, style, (W, H), secs)


def frame(sc, t):
    import cairo

    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    sc.render(cairo.Context(surf), t, cairo)
    surf.flush()
    d = bytes(surf.get_data())
    return [(d[i + 2], d[i + 1], d[i]) for i in range(0, len(d), 4)]


@unittest.skipUnless(A.available(), "нет pycairo")
class Action(unittest.TestCase):
    def test_style_is_found(self):
        self.assertEqual(ST.find("сделай экшен"), "action")
        self.assertEqual(ST.find("драка стикменов"), "action")
        self.assertIn("action", A.LOOKS)

    def test_thick_outlined_figure(self):
        sc = scene({"actors": [{"id": "a", "x": 0.5}]})
        px = frame(sc, 1.0)
        cyan = sum(1 for r, g, b in px if g > 180 and b > 180 and r < 100)
        self.assertGreater(cyan, 900)                                     # толстые линии и залитая голова — много цвета

    def test_camera_follows_and_stays_inside_the_screen(self):
        far = scene({"actors": [{"id": "a", "x": 0.1}, {"id": "b", "x": 0.9}]}).cam(2.0)
        near = scene({"actors": [{"id": "a", "x": 0.45}, {"id": "b", "x": 0.55}]}).cam(2.0)
        self.assertEqual(far[0], 1.0)                                     # далеко друг от друга — общий план
        self.assertGreater(near[0], 1.2)                                  # сошлись — камера ближе
        z, cx, cy, _ = near
        self.assertTrue(W / 2 / z <= cx <= W - W / 2 / z and H / 2 / z <= cy <= H - H / 2 / z)

    def test_big_hit_punch_in_negative_frame_and_hitstop(self):
        sc = scene()
        big = next(k for k in sc.knocks if k["big"])
        self.assertGreater(sc.cam(big["t"] + 0.02)[0], sc.cam(big["t"] - 0.3)[0])   # рывок камеры на ударе
        before, at = frame(sc, big["t"] - 0.2), frame(sc, big["t"] + 0.01)
        bright = lambda px: sum(r + g + b for r, g, b in px[::7]) / len(px[::7])   # noqa: E731
        self.assertGreater(bright(at), bright(before) * 3)                # кадр-негатив: тёмный стол стал светлым
        self.assertEqual(sc.stops(), [big["t"]])
        self.assertEqual(sc.scene_time(big["t"] + 0.05), big["t"])        # сцена замерла на ударе
        self.assertAlmostEqual(sc.scene_time(big["t"] + 0.5), big["t"] + 0.5 - sc.HITSTOP)
        self.assertAlmostEqual(sc.video_time(big["t"] + 1.0), big["t"] + 1.0 + sc.HITSTOP)
        self.assertEqual(scene(style="neon_desktop").stops(), [])          # в других стилях паузы нет

    def test_smear_and_sparks_draw(self):
        import cairo

        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 100, 100)
        c = cairo.Context(surf)
        A.draw_smear(c, (10, 10), (60, 60), 8, (1, 0, 0))
        A.draw_sparks(c, (50, 50), 0.05, 80, 1)
        A.draw_sparks(c, (50, 50), 0.4, 80, 1)
        A.draw_sparks(c, (50, 50), 0.9, 80, 1)                            # после 0,6 с — ничего, без ошибок
        sc = scene()
        for i in range(0, 120, 3):
            sc.render(cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)), i / 25, cairo)
        self.assertIn("a", sc._prev)                                      # растяжки помнят прошлый кадр


if __name__ == "__main__":
    unittest.main()
