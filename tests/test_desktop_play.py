"""Мультики на рабочем столе: курсор-персонаж, окна (тащат, бьют, разбивают), герой на курсоре, следы, вспышка, звуки."""
import unittest

from chloe import animator as A
from chloe import desktop_play as DP

W, H = 640, 360
SPEC = {"actors": [{"id": "byte", "x": 0.3}],
        "windows": [{"id": "w1", "x": 0.6, "y": 0.2, "w": 0.2, "h": 0.2}],
        "acting": [{"who": "byte", "do": "punch", "from": 0.3, "to": 0.45, "target": "w1"}],
        "cursor": [{"t": 0.0, "x": 0.9, "y": 0.1}, {"t": 0.1, "x": 0.65, "y": 0.22, "grab": "w1"},
                   {"t": 0.2, "x": 0.45, "y": 0.4, "release": True},
                   {"t": 0.55, "x": 0.3, "y": 0.5, "grab": "byte"}, {"t": 0.7, "x": 0.6, "y": 0.2, "release": True}]}


def scene(spec=SPEC, secs=10.0):
    return A.Scene(spec, "neon_desktop", (W, H), secs)


class CursorAndWindows(unittest.TestCase):
    def test_cursor_path_and_grabs(self):
        cur = scene().cursor
        self.assertEqual(cur.pos(0.0), (0.9 * W, 0.1 * H))
        self.assertAlmostEqual(cur.pos(2.0)[0], 0.45 * W)
        self.assertEqual(cur.holding(1.5), ("w1", 1.0))
        self.assertEqual(cur.holding(3.0), (None, None))
        self.assertEqual(cur.presses(), [1.0, 5.5])

    def test_window_follows_drag_and_stays(self):
        sc = scene()
        x0, y0, _, _ = sc.windows.rect("w1", 0.5)
        x1, y1, _, _ = sc.windows.rect("w1", 2.5)
        self.assertEqual((x0, y0), (0.6 * W, 0.2 * H))
        self.assertAlmostEqual(x1 - x0, (0.45 - 0.65) * W, delta=1)
        self.assertAlmostEqual(y1 - y0, (0.4 - 0.22) * H, delta=1)
        self.assertEqual(sc.windows.rect("w1", 2.5), sc.windows.rect("w1", 3.5))

    def test_punch_breaks_the_window_on_the_hit_frame(self):
        sc = scene()
        tb, _ = sc.windows.broken["w1"]
        self.assertAlmostEqual(tb, 3.0 + A.STRIKE['punch'][1] / 1.6, places=3)
        self.assertEqual(len(sc.windows.shards["w1"]), 24)
        no_target = dict(SPEC, acting=[dict(SPEC["acting"][0], target=None)])
        self.assertEqual(scene(no_target).windows.broken, {})

    def test_hero_hangs_then_falls_where_dropped(self):
        sc = scene()
        hang = sc.carried("byte", 6.0)
        self.assertFalse(hang["falling"])
        self.assertAlmostEqual(hang["head"][0], sc.cursor.pos(6.0)[0])
        self.assertTrue(sc.carried("byte", 7.05)["falling"])
        self.assertIsNone(sc.carried("byte", 9.5))                         # уже на земле
        self.assertAlmostEqual(sc.where("byte", 9.5)[0], 0.6, places=2)    # там, где отпустили
        self.assertAlmostEqual(sc.where("byte", 4.0)[0], 0.3, places=2)

    def test_sounds_of_the_interface(self):
        ev = scene().sound_events()
        kinds = {e["kind"]: e["t"] for e in ev}
        self.assertEqual(sorted(e["t"] for e in ev if e["kind"] == "click"), [1.0, 5.5])
        self.assertAlmostEqual(kinds["shatter"], 3.0 + A.STRIKE['punch'][1] / 1.6, places=3)
        lands = [e["t"] for e in ev if e["kind"] == "thud"]
        self.assertTrue(any(7.0 < t < 8.0 for t in lands))
        self.assertTrue(DP.fall_time(100, H) > DP.fall_time(10, H) > 0)


class CursorCharacter(unittest.TestCase):
    SPEC = {"actors": [{"id": "byte", "x": 0.4}],
            "cursor": [{"t": 0.0, "x": 0.9, "y": 0.1}, {"t": 0.2, "x": 0.8, "y": 0.2, "mood": "angry"},
                       {"t": 0.25, "hit": "byte"}, {"t": 0.4, "x": 0.5, "y": 0.2, "mood": "happy"},
                       {"t": 0.6, "grab": "byte", "by": "foot"}, {"t": 0.75, "x": 0.5, "y": 0.15},
                       {"t": 0.85, "x": 0.6, "y": 0.15, "release": True}]}

    def scene(self):
        return A.Scene(self.SPEC, "neon_desktop", (W, H), 10.0)

    def test_moods(self):
        cur = self.scene().cursor
        self.assertEqual([cur.mood(t) for t in (1.0, 2.5, 4.5)], ["calm", "angry", "happy"])

    def test_fast_dart_winds_up_first(self):
        cur = self.scene().cursor
        a, b = cur.keys[1], cur.keys[2]                                    # к герою — быстрый бросок
        x_early = cur.pos(a["t"] + 0.15 * (b["t"] - a["t"]))[0]
        self.assertGreater(x_early, a["x"])                                # сначала назад (герой левее)

    def test_cursor_punches_the_hero(self):
        sc = self.scene()
        k = next(k for k in sc.knocks if k["by"] == "cursor")
        self.assertEqual((k["t"], k["dir"], k["big"]), (2.5, -1, True))
        self.assertAlmostEqual(sc.cursor.keys[2]["x"], 0.4 * W)             # прилетел туда, где стоял герой
        self.assertTrue(any(e["kind"] == "punch" and e["t"] == 2.5 for e in sc.sound_events()))

    def test_grab_by_foot_where_the_hero_is_now(self):
        sc = self.scene()
        after = sc.where("byte", 5.9)[0]
        self.assertLess(after, 0.4 - 0.15)                                  # его отбросило влево
        grab = sc.cursor.keys[4]
        self.assertAlmostEqual(grab["x"], after * W, delta=1)               # курсор ищет его на новом месте
        self.assertEqual(sc.carried("byte", 6.5)["by"], "foot")
        fall = sc.carried("byte", 8.55)
        self.assertTrue(fall["falling"])
        self.assertGreater(fall["flip"], 0)                                 # в полёте переворачивается на ноги


class LiveDesktop(unittest.TestCase):
    SPEC = {"actors": [{"id": "byte", "x": 0.55}],
            "acting": [{"who": "byte", "do": "cheer", "from": 0.85, "to": 1.0}],
            "cursor": [{"t": 0.0, "x": 0.8, "y": 0.1}, {"t": 0.1, "click": "start"},
                       {"t": 0.25, "grab": "music"}, {"t": 0.3, "x": 0.1, "y": 0.3},
                       {"t": 0.36, "x": 0.4, "y": 0.42, "release": True},
                       {"t": 0.6, "grab": "byte"}, {"t": 0.72, "x": 0.965, "y": 0.6, "release": True}]}

    def scene(self):
        return A.Scene(self.SPEC, "neon_desktop", (W, H), 12.0)

    def test_default_icons_and_no_fake_windows(self):
        sc = self.scene()
        self.assertEqual(sc.icons.ids(), ["folder", "file", "music", "trash"])
        self.assertTrue(sc.live_desktop)
        self.assertFalse(A.Scene({"actors": [{"id": "a"}]}, "neon_desktop", (W, H), 4.0).live_desktop)

    def test_cursor_finds_start_and_menu_opens(self):
        sc = self.scene()
        click = sc.cursor.keys[1]
        self.assertLess(click["x"], W * 0.1)
        self.assertGreater(click["y"], sc.ground)                          # на панели задач
        self.assertEqual(sc.menu_open(1.0), 0.0)
        self.assertEqual(sc.menu_open(2.0), 1.0)
        self.assertEqual(sc.menu_open(3.2), 0.0)

    def test_thrown_icon_flies_hits_and_bounces(self):
        sc = self.scene()
        t, victim, d = sc.icons.hits_on[0]
        self.assertEqual((victim, d), ("byte", 1))
        self.assertTrue(4.32 < t < 6.0)
        self.assertTrue(any(k["by"] == "icon" for k in sc.knocks))
        x, y, _ = sc.icons.at("music", 11.9)
        self.assertAlmostEqual(y + sc.icons.size, sc.ground, delta=1)       # легла на панель задач
        self.assertTrue(sc.icons.bounces)
        kinds = [e["kind"] for e in sc.sound_events()]
        self.assertIn("tap", kinds)
        self.assertIn("pop", kinds)                                        # меню «Пуск»

    def test_cursor_dives_into_trash(self):
        spec = dict(self.SPEC, cursor=self.SPEC["cursor"] + [{"t": 0.9, "into": "trash"}])
        sc = A.Scene(spec, "neon_desktop", (W, H), 12.0)
        r = sc.icons.trash_rect(10.8)
        x, y = sc.cursor.pos(10.8)
        self.assertTrue(r[0] <= x <= r[0] + r[2])
        self.assertFalse(sc.cursor.gone(10.8))
        self.assertTrue(sc.cursor.gone(11.5))
        self.assertIn("boop", [e["kind"] for e in sc.sound_events()])
        import cairo

        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        for t in (10.9, 11.5):
            sc.render(cairo.Context(surf), t, cairo)

    def test_trash_swallows_and_pops_out(self):
        sc = self.scene()
        tin, tout = sc.trashed["byte"]
        self.assertEqual((tin, tout), (8.64, 10.2))
        self.assertTrue(sc.is_hidden("byte", 9.5))
        self.assertFalse(sc.is_hidden("byte", 10.3))
        self.assertIsNone(sc.carried("byte", 8.8))                         # не падает — проваливается
        self.assertLess(sc.where("byte", 11.5)[0], sc.where("byte", 9.0)[0])   # выпрыгнул влево


@unittest.skipUnless(A.available(), "нет pycairo")
class Frames(unittest.TestCase):
    def brightness(self, sc, t):
        import cairo

        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        c = cairo.Context(surf)
        sc.render(c, t, cairo)
        surf.flush()
        data = surf.get_data()
        return sum(data[i] for i in range(0, len(data), 16)) / (len(data) / 16)

    def test_flash_on_the_hit_and_every_moment_renders(self):
        sc = scene()
        tb, _ = sc.windows.broken["w1"]
        self.assertGreater(self.brightness(sc, tb + 0.005), self.brightness(sc, tb + 0.3) + 5)
        for t in (0.0, 1.5, 3.2, 4.0, 6.0, 7.1, 9.9):                       # перенос, осколки, висит, падает
            self.brightness(sc, t)
        live = A.Scene(LiveDesktop.SPEC, "neon_desktop", (W, H), 12.0)
        for t in (1.5, 4.0, 5.0, 8.0, 8.8, 9.5, 10.4):                     # меню, полёт иконки, корзина
            self.brightness(live, t)
        cc = A.Scene(CursorCharacter.SPEC, "neon_desktop", (W, H), 10.0)
        for t in (2.2, 2.5, 4.5, 6.2, 7.0, 8.55, 9.5):                     # злой, удар, весёлый, за ногу, бросок
            self.brightness(cc, t)


if __name__ == "__main__":
    unittest.main()
