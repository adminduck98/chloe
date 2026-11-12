"""Игровой мир: экран выбора уровня с кнопкой Play, уровень с прокруткой, шипы, балки, порталы, гравитация, исчезновение
в кнопке и падение в мир, вспышки, затемнения, надписи, звуки."""
import unittest

from chloe import animator as A
from chloe import game_world as GW

W, H = 640, 360


def scene(game, acting=(), secs=8.0):
    return A.Scene({"actors": [{"id": "hero", "x": 0.3, "color": "green"}], "game": game, "acting": list(acting)},
                   "action", (W, H), secs)


def frame(sc, t):
    import cairo

    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    sc.render(cairo.Context(surf), t, cairo)
    surf.flush()
    d = bytes(surf.get_data())
    return [(d[i + 2], d[i + 1], d[i]) for i in range(0, len(d), 4)]


@unittest.skipUnless(A.available(), "нет pycairo")
class GameWorld(unittest.TestCase):
    def test_scroll_and_gravity(self):
        sc = scene({"world": "level", "scroll": [{"from": 0.25, "to": 0.75, "speed": 0.4}],
                    "gravity": [{"t": 0.5, "up": True}]})
        self.assertEqual(sc.scroll(1.0), 0.0)
        self.assertAlmostEqual(sc.scroll(4.0), 0.4 * 2.0)
        self.assertAlmostEqual(sc.scroll(8.0), 0.4 * 4.0)
        self.assertEqual(sc.gravity(3.9), 1.0)
        self.assertEqual(sc.gravity(5.0), -1.0)                          # перевернулась
        self.assertTrue(-1.0 < sc.gravity(4.15) < 1.0)                   # переворот плавный
        self.assertIsNone(sc.look["camera"])                              # в игре камера стоит

    def test_vanish_and_drop_in(self):
        sc = scene({"world": "select", "play": {"x": 0.7, "y": 0.6}},
                   [{"who": "hero", "do": "drop_in", "from": 0.1, "to": 0.2},
                    {"who": "hero", "do": "vanish", "from": 0.6, "to": 0.7, "into": [0.7, 0.6]}])
        self.assertTrue(sc.is_hidden("hero", 0.5))                       # ещё не упал в мир
        self.assertFalse(sc.is_hidden("hero", 3.0))
        self.assertTrue(sc.is_hidden("hero", 6.0))                       # затянуло в кнопку
        kinds = [e["kind"] for e in sc.sound_events()]
        self.assertIn("thud", kinds)                                     # приземлился
        self.assertIn("whoosh", kinds)                                   # затянуло

    def test_screens_render(self):
        sel = scene({"world": "select", "play": {"x": 0.7, "y": 0.6, "press": 0.5, "glow": [[0.4, 0.6]]}, "new_level": 0.3,
                     "flash": [0.55]})
        lvl = scene({"world": "level", "spikes": [0.5], "ceiling_spikes": [0.6], "barriers": [0.8], "portals": [{"x": 0.9}],
                     "play": {"x": 0.7, "y": 0.6}, "fade_in": [[0.0, 0.1]], "fade_out": [[0.9, 1.0]],
                     "titles": [{"from": 0.95, "to": 1.0, "text": "TO BE CONTINUED..."}]})
        bright = lambda px: sum(r + g + b for r, g, b in px[::9]) / len(px[::9])   # noqa: E731
        self.assertGreater(bright(frame(sel, 4.45)), bright(frame(sel, 1.0)) + 30)   # вспышка
        self.assertLess(bright(frame(lvl, 0.0)), 5)                     # из темноты
        self.assertGreater(bright(frame(lvl, 3.0)), 60)
        end = frame(lvl, 7.95)
        self.assertTrue(any(r > 120 and g > 120 and b > 120 for r, g, b in end))   # надпись проявляется на чёрном
        self.assertTrue(any(r > 200 and g < 100 for r, g, b in frame(lvl, 3.0)))   # красный шип

    def test_play_button_sounds(self):
        sc = scene({"world": "select", "play": {"x": 0.7, "y": 0.6, "press": 0.5}, "new_level": 0.2,
                    "gravity": [{"t": 0.3}], "flash": [0.6]})
        kinds = [e["kind"] for e in sc.sound_events()]
        for k in ("click", "pop", "ding", "boop", "sparkle"):
            self.assertIn(k, kinds)

    def test_leap_is_high_and_dodges(self):
        p, _ = A.action_pose("leap", 0.45, 0.9)
        self.assertGreater(p["dy"], 0.3)
        from chloe import mocap as MC
        self.assertIn("leap", MC.DODGE)


if __name__ == "__main__":
    unittest.main()
