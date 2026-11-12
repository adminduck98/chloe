"""Постановщик драк: такты → движения со временем, блоки, уклоны (промах — только свист), лёгкие и сильные удары."""
import unittest

from chloe import animator as A
from chloe import choreo as C

FIGHT = {"from": 0.05, "to": 0.95, "beats": [
    {"who": "hero", "move": "punch", "answer": "guard"},
    {"who": "rival", "move": "kick", "answer": "duck"},
    {"who": "hero", "move": "punch", "answer": "hit", "power": "light"},
    {"who": "rival", "move": "taunt"},
    {"who": "hero", "move": "spinkick", "answer": "hit", "power": "heavy"}]}
SPEC = {"actors": [{"id": "hero", "x": 0.3}, {"id": "rival", "x": 0.6, "facing": "left"}], "fight": FIGHT}


def scene(spec=SPEC, secs=14.0, style="neon_desktop"):
    return A.Scene(spec, style, (1280, 720), secs)


class Expand(unittest.TestCase):
    def test_beats_become_timed_moves(self):
        out = C.expand(FIGHT, ["hero", "rival"], 14.0)
        moves = [(s["who"], s["do"]) for s in out]
        self.assertIn(("hero", "punch"), moves)
        self.assertIn(("rival", "guard"), moves)                         # ответ противника — блок
        self.assertIn(("hero", "duck"), moves)
        self.assertIn(("rival", "angry"), moves)                         # «дразнит»
        strikes = [s for s in out if s["do"] in C.STRIKES]
        self.assertTrue(all(s["target"] for s in strikes))
        starts = [s["from"] for s in out if not s.get("_answer")]
        self.assertEqual(starts, sorted(starts))                         # такты — по порядку
        self.assertTrue(all(0 <= s["from"] < s["to"] <= 1 for s in out))

    def test_answer_covers_the_hit(self):
        sc = scene()
        kick_t = next(t for t, a, s in sc.hit_times() if a == "rival")
        self.assertTrue(sc.dodging("hero", kick_t))                      # пригнулся ровно на ударе

    def test_short_scene_squeezes_or_drops_beats(self):
        full = C.expand(FIGHT, ["hero", "rival"], 14.0)
        short = C.expand(FIGHT, ["hero", "rival"], 4.0)
        self.assertLess(len(short), len(full))
        self.assertTrue(all(s["to"] <= 0.95 + 1e-6 for s in short))

    def test_needs_two_fighters(self):
        self.assertEqual(C.expand(FIGHT, ["hero"], 10.0), [])


class Outcome(unittest.TestCase):
    def test_block_miss_light_and_heavy(self):
        sc = scene()
        kinds = {(round(k["t"], 2), k["who"]): ("block" if k.get("blocked") else "big" if k["big"] else "light") for k in sc.knocks}
        self.assertEqual(sorted(kinds.values()), ["big", "block", "light"])
        rival_kick = next(t for t, a, s in sc.hit_times() if a == "rival")
        ev = [e for e in sc.sound_events() if abs(e["t"] - rival_kick) < 0.02]
        self.assertFalse(any(e["kind"] == "punch" for e in ev))           # промах — без звука удара
        self.assertTrue(any(e["kind"] == "swish" for e in sc.sound_events() if abs(e["t"] - (rival_kick - 0.05)) < 0.02))

    def test_synonyms_and_unknown_words(self):
        out = C.expand({"beats": [{"who": "hero", "move": "flying_kick", "answer": "dodge"}, {"who": "rival", "move": "dance?"}]},
                       ["hero", "rival"], 10.0)
        self.assertEqual(out[0]["do"], "duck")                           # dodge → уклон
        self.assertTrue(any(s["do"] == "jumpkick" for s in out))


if __name__ == "__main__":
    unittest.main()
