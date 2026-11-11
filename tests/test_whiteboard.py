"""Белая доска: тёплая бумага, маркер рисует по порядку рассказа и по словам голоса, заливки — контуром, скрип маркера."""
import unittest

from chloe import animator as A
from chloe import sfx as S
from chloe import stickman_styles as ST

SPEC = {"actors": [{"id": "anya", "x": 0.3}, {"id": "bob", "x": 0.7, "color": "green"}],
        "props": [{"kind": "table", "x": 0.5}, {"kind": "tree", "x": 0.85}],
        "acting": [{"who": "anya", "do": "point", "from": 0.7, "to": 1}]}


def scene(spec=SPEC, words=None, secs=8.0):
    return A.Scene(spec, "whiteboard", (320, 180), secs, words=words)


def frame(sc, t):
    import cairo

    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, sc.w, sc.h)
    c = cairo.Context(surf)
    sc.render(c, t, cairo)
    surf.flush()
    data = bytes(surf.get_data())
    return [(data[i + 2], data[i + 1], data[i]) for i in range(0, len(data), 4)]


@unittest.skipUnless(A.available(), "нет pycairo")
class Board(unittest.TestCase):
    def test_style_is_found_by_words(self):
        self.assertEqual(ST.find("нарисуй на белой доске"), "whiteboard")
        self.assertEqual(ST.find("маркером"), "whiteboard")
        self.assertEqual(ST.find("в светлом стиле"), "classic_light")

    def test_order_place_first_then_heroes_and_ready_by_sixty_percent(self):
        plan = scene().plan
        order = sorted(plan, key=lambda k: plan[k][0])
        self.assertEqual(order[:3], ["ground", "prop:0", "prop:1"])
        self.assertEqual(set(order[3:]), {"anya", "bob"})
        self.assertLessEqual(max(t1 for _t0, t1 in plan.values()), 8.0 * 0.6 + 0.01)
        for a, b in zip(order, order[1:]):
            self.assertLessEqual(plan[a][1], plan[b][0] + 1e-6)           # одна рука — части по очереди

    def test_drawing_follows_the_voice(self):
        spec = dict(SPEC, draw=[{"what": "tree", "word": "дерево"}, {"what": "anya", "word": "Аня"}])
        words = [(0.0, 0.4, "Вот"), (2.0, 2.5, "деревья,"), (5.0, 5.3, "Аня.")]
        plan = scene(spec, words).plan
        self.assertEqual(plan["prop:1"][0], 2.0)
        self.assertEqual(plan["anya"][0], 5.0)

    def test_blank_paper_first_full_picture_at_the_end(self):
        sc = scene()
        first, last = frame(sc, 0.0), frame(sc, 7.9)
        paper = first[0]
        self.assertTrue(all(abs(p[0] - 245) < 4 and abs(p[2] - 215) < 5 for p in (paper,)))   # #F5EBD7
        self.assertEqual(set(first), {paper})                              # первый кадр — чистая бумага
        self.assertGreater(sum(p != paper for p in last), 300)

    def test_part_appears_gradually_with_a_marker(self):
        sc = scene()
        t0, t1 = sc.plan["prop:0"]
        paper = frame(sc, 0.0)[0]

        def ink(t):
            return sum(p != paper for p in frame(sc, t))

        self.assertLess(ink(t0 + 0.3 * (t1 - t0)), ink(t0 + 0.8 * (t1 - t0)))
        self.assertLess(ink(t0 + 0.8 * (t1 - t0)), ink(t1 + 0.4) + 400)    # маркер в кадре добавляет своё

    def test_palette_and_sketch_props(self):
        sc = scene()
        self.assertEqual(sc.actors["bob"]["color"], A.COLORS["red"])     # зелёного на доске нет — первый акцент
        self.assertIsNone(A._accent_of(A.COLORS["green"]))               # зелёная крона — контур маркером
        self.assertEqual(A._accent_of((0.98, 0.75, 0.18)), A.COLORS["orange"])
        last = frame(sc, 7.9)
        greens = sum(1 for r, g, b in last if g > r + 60 and g > b + 60)
        self.assertEqual(greens, 0)

    def test_camera_stands_still(self):
        sc = A.Scene(dict(SPEC, shot="close"), "whiteboard", (320, 180), 8.0)
        self.assertEqual(sc.cam(4.0)[0], 1.0)

    def test_marker_scribbles(self):
        ev = scene().sound_events()
        scr = [e for e in ev if e["kind"] == "scribble"]
        self.assertEqual(len(scr), 5)                                      # земля, стол, дерево и двое героев
        x, _ = S.make("scribble", 3, dur=1.0)
        self.assertEqual(S.check(x), [])
        self.assertAlmostEqual(len(x) / S.SR, 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
