"""Peach & Puff World: 15 утверждённых мест, выбор места, история серий и изменения в мире до уборки."""
import json
import unittest

from chloe import doodle_short as DS
from chloe import peach_world as W


class World(unittest.TestCase):
    def setUp(self):
        for p in (W.HISTORY, W.STATE):
            p.unlink(missing_ok=True)
        self.addCleanup(lambda: [p.unlink(missing_ok=True) for p in (W.HISTORY, W.STATE)])

    def test_canon_locations(self):
        locs = W.locations()
        self.assertEqual(len(locs), 15)
        self.assertIn("exactly two chairs", locs["kitchen"]["prompt"])
        self.assertIn("диван напротив телевизора", locs["living_room"]["fixed"])
        self.assertEqual(W.guess("Персик печёт торт"), "kitchen")
        self.assertEqual(W.guess("идут в кафе Две кружки"), "two_little_cups")
        self.assertEqual(W.guess("что-то непонятное"), "living_room")

    def test_history_and_props_until_cleaned(self):
        n1 = W.record({"title": "Торт", "location": "kitchen", "beats": [{"words": "Это не я!"}],
                       "world_changes": ["кухня: пятно от крема на столе"]})
        self.assertEqual(n1, 1)
        self.assertIn("кухня: пятно от крема на столе", W.continuity())
        self.assertIn("№1 «Торт» (Кухня)", W.continuity())
        W.record({"title": "Уборка", "location": "kitchen", "beats": [], "world_fixed": ["кухня: пятно от крема на столе"]})
        self.assertNotIn("пятно", W.continuity())
        self.assertEqual([e["n"] for e in W.history()], [1, 2])

    def test_plan_location_from_approved_map(self):
        reply = json.dumps({"title": "Кафе", "scene": "cafe", "location": "two_little_cups",
                            "beats": [{"words": "Торт!", "seconds": 4, "motion": "m"}]})
        self.assertEqual(DS.parse_plan(reply, 20)["location"], "two_little_cups")
        reply = json.dumps({"title": "Торт на кухне", "scene": "x", "location": "moon_base",
                            "beats": [{"words": "Торт!", "seconds": 4, "motion": "m"}]})
        self.assertEqual(DS.parse_plan(reply, 20)["location"], "kitchen")   # выдуманное место — нельзя


if __name__ == "__main__":
    unittest.main()
