"""Отпечаток голоса владельца: набирается из фраз с «Хлоя» и по «запомни мой голос»; голос владельца — ей и без
имени, чужой — только по имени; при заучивании фразы не выполняются как команды. Модель подменена векторами."""
import time
import unittest
from unittest import mock

import numpy as np

from chloe import voiceprint as VP
from chloe.signals import busy, state
from chloe.voice import route_phrase, voice

voice.enabled = False
OWNER = np.array([1.0, 0.2, 0.1] + [0.0] * 253, np.float32)
GUEST = np.array([0.1, 1.0, 0.3] + [0.0] * 253, np.float32)


class Audio:
    def __init__(self, who, local=""):
        self.who, self.local = who, local
        self.frame_data = b"\0\0" * 32000
        self.sample_rate, self.sample_width = 16000, 2


def fake_embed(audio):
    v = (OWNER if audio.who == "owner" else GUEST) + np.random.default_rng(len(audio.local)).normal(0, 0.02, 256)
    return (v / np.linalg.norm(v)).astype(np.float32)


class Voiceprint(unittest.TestCase):
    def setUp(self):
        VP.reset()
        for p in (mock.patch.object(VP, "embed", side_effect=fake_embed), mock.patch.object(VP, "available", return_value=True),
                  mock.patch.object(VP, "MODE", "voice"), mock.patch("chloe.voice.ears.hear", side_effect=lambda a: a.local)):
            p.start()
            self.addCleanup(p.stop)
        busy.clear()
        state["listen_until"] = 0.0
        voice.saying, voice.spoke_until, voice.awaiting, voice.open_until, voice.reason, voice.enroll_until = "", 0.0, False, 0.0, "", 0.0
        self.addCleanup(VP.reset)

    def learn_owner(self, n=VP.MIN_SAMPLES):
        for i in range(n):
            self.assertTrue(VP.learn(Audio("owner", "x" * i)))

    def test_not_ready_until_enough_samples(self):
        self.learn_owner(VP.MIN_SAMPLES - 1)
        self.assertFalse(VP.ready())
        self.assertEqual(route_phrase(Audio("owner", "какая погода"), time.time()), "skip")   # пока только по имени
        self.learn_owner(1)
        self.assertTrue(VP.ready())

    def test_owner_without_name_guest_only_with_name(self):
        self.learn_owner()
        self.assertEqual(route_phrase(Audio("owner", "какая погода"), time.time()), "cloud")
        self.assertEqual(voice.reason, "owner")
        voice.reason = ""
        self.assertEqual(route_phrase(Audio("guest", "какая погода"), time.time()), "skip")
        self.assertEqual(route_phrase(Audio("guest", "хлоя какая погода"), time.time()), "cloud")

    def test_owner_recognised_in_continuation_too(self):
        """Журнал 16.11.2026: фраза сразу после прошлой шла как «продолжение» мимо узнавания и отбрасывалась."""
        self.learn_owner()
        voice.open_until = time.time() + 5
        self.assertEqual(route_phrase(Audio("owner", "какая погода"), time.time()), "cloud")
        self.assertEqual(voice.reason, "owner")

    def test_guest_saying_name_does_not_pollute_profile(self):
        self.learn_owner()
        self.assertFalse(VP.learn(Audio("guest", "хлоя привет")))
        self.assertEqual(len(VP.samples()), VP.MIN_SAMPLES)

    def test_enroll_window_listens_but_does_not_act(self):
        voice.enroll_until = time.time() + 5
        with mock.patch("chloe.voice.threading.Thread") as th:
            self.assertEqual(route_phrase(Audio("owner", "раз два три"), time.time()), "skip")
        self.assertIs(th.call_args.kwargs["target"], VP.learn)

    def test_name_mode_switch(self):
        self.learn_owner()
        with mock.patch.object(VP, "MODE", "name"):
            self.assertEqual(route_phrase(Audio("owner", "какая погода"), time.time()), "skip")


class Heard(unittest.TestCase):
    def test_owner_flag(self):
        from chloe.signals import Heard as H

        self.assertTrue(H("привет", 1.0, True).owner)
        self.assertFalse(H("привет").owner)


if __name__ == "__main__":
    unittest.main()
