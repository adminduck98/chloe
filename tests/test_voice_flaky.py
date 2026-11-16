"""Светлана сбоит (Microsoft ограничивает бесплатный сервис): два сбоя за 5 минут — 10 минут сразу запасной голос."""
import time
import unittest
from unittest import mock

from chloe import speech_stream as SS
from chloe.voice import voice


class Flaky(unittest.TestCase):
    def setUp(self):
        SS.failures.clear()
        voice.voice_down_until = 0.0
        self.addCleanup(SS.failures.clear)
        self.addCleanup(setattr, voice, "voice_down_until", 0.0)

    def test_two_recent_failures(self):
        self.assertFalse(SS.flaky())
        SS.failures.append(time.time() - 1000)            # давний сбой не считается
        SS.failures.append(time.time())
        self.assertFalse(SS.flaky())
        SS.failures.append(time.time())
        self.assertTrue(SS.flaky())

    def test_switches_to_backup_for_ten_minutes(self):
        SS.failures += [time.time(), time.time()]
        with mock.patch("chloe.voice.phrase_cache.get", return_value=None):
            self.assertFalse(voice._say_edge("Длинный ответ, который Светлана сейчас не скажет."))
        self.assertGreater(voice.voice_down_until, time.time() + 500)


if __name__ == "__main__":
    unittest.main()
