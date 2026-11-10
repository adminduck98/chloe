"""Приветствие при запуске: по времени суток, с обращением из памяти, без повторов подряд."""
import random
import time
import unittest
from unittest import mock

from chloe import greeting as g
from chloe.settings import settings


def at(hour):
    return time.mktime(time.strptime("2026-11-11 {:02d}:10".format(hour), "%Y-%m-%d %H:%M"))


class Greeting(unittest.TestCase):
    def setUp(self):
        settings.set("last_greeting", None)

    def test_part_of_day(self):
        self.assertEqual([g.part_of_day(h) for h in (1, 4, 5, 11, 12, 17, 18, 22, 23)],
                         ["night", "night", "morning", "morning", "day", "day", "evening", "evening", "night"])

    def test_never_the_old_fixed_phrase_and_no_repeat(self):
        rnd = random.Random(1)
        with mock.patch.object(g, "address", return_value=""):
            seen = [g.greeting(at(14), rnd=rnd) for _ in range(30)]
        self.assertNotIn("Привет, я Хлоя. Слушаю.", seen)
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])))          # подряд — не одно и то же
        self.assertGreater(len(set(seen)), 8)
        self.assertFalse(any("Я здесь" in x and "Я слушаю" in x for x in seen))

    def test_time_of_day_words(self):
        with mock.patch.object(g, "address", return_value=""):
            self.assertTrue(g.greeting(at(8), rnd=random.Random(2)).lower().startswith(("доброе утро", "утро доброе", "с добрым утром")))
            self.assertIn("вечер", g.greeting(at(20), rnd=random.Random(3)).lower())
            self.assertIn("утр", g.greeting(at(8), brief=True, rnd=random.Random(4)).lower())

    def test_address_from_memory(self):
        from chloe.memory import memory

        with mock.patch.object(memory, "items", [{"text": "Пользователь не любит сериалы. Обращаться к нему «босс».", "id": 1}]):
            self.assertEqual(g.address(), "босс")
            texts = [g.greeting(at(14), rnd=random.Random(i)) for i in range(20)]
        self.assertTrue(any(", босс" in t for t in texts))
        with mock.patch.object(memory, "items", []):
            self.assertEqual(g.address(), "")


if __name__ == "__main__":
    unittest.main()
