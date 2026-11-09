"""Офлайн-слово «Хлоя»: в Google уходит только сказанное Хлое. Остальная речь в комнате не покидает компьютер."""
import audioop
import io
import os
import pathlib
import time
import unittest
import wave
from unittest import mock

from chloe import config
from chloe.ears import Ears, has_wake
from chloe.signals import busy, state
from chloe.voice import CONTINUE_MAX, open_continuation, route_phrase, voice

voice.enabled = False
REAL = pathlib.Path(os.environ.get("CHLOE_REAL_HOME", "/nonexistent")) / ".chloe"
VOSK = REAL / "ears" / config.EARS_MODEL
PIPER = REAL / "voices" / (config.PIPER_VOICE + ".onnx")


class Audio:
    """Похожа на запись speech_recognition: длина считается по байтам."""
    def __init__(self, seconds=2.0, local=""):
        self.frame_data = b"\0\0" * int(16000 * seconds)
        self.sample_rate, self.sample_width, self.local = 16000, 2, local


class Route(unittest.TestCase):
    def setUp(self):
        self.heard = []   # что офлайн-слух успел распознать
        p = mock.patch("chloe.voice.ears.hear", side_effect=lambda a: self.heard.append(a.local) or a.local)
        p.start()
        self.addCleanup(p.stop)
        busy.clear()
        state["listen_until"] = 0.0
        voice.saying, voice.spoke_until, voice.awaiting, voice.open_until = "", 0.0, False, 0.0
        config.WAKE_OFFLINE = True
        self.addCleanup(busy.clear)
        self.addCleanup(self.reset_voice)   # не оставлять «ждёт да/нет» и открытое окно следующим тестам

    @staticmethod
    def reset_voice():
        voice.saying, voice.spoke_until, voice.awaiting, voice.open_until, voice.open_origin, voice.reason = "", 0.0, False, 0.0, 0.0, ""

    def way(self, local, seconds=2.0, started_ago=0.0):
        return route_phrase(Audio(seconds, local), time.time() - started_ago)

    def test_room_talk_stays_on_computer(self):
        for talk in ("мы вчера играли в доту на инвокере", "хлопья на завтрак", "клоун пришёл", ""):
            self.assertEqual(self.way(talk), "skip", talk)

    def test_wake_word_anywhere(self):
        for talk in ("хлоя какая погода", "сделай погромче хлоя", "ну и как тебе хлоя", "у хлои есть"):
            self.assertEqual(self.way(talk), "cloud", talk)

    def test_after_her_answer_no_wake_needed(self):
        state["listen_until"] = time.time() + 10
        self.assertEqual(self.way("а завтра"), "cloud")
        self.assertEqual(self.heard, [])   # даже офлайн-слух не понадобился

    def test_rest_of_the_phrase_follows(self):
        voice.open_until = time.time() + 1
        self.assertEqual(self.way("в папку документы", started_ago=0.5), "cloud")

    def test_tv_cannot_keep_the_door_open(self):
        """Видео говорит без пауз: после «Хлоя» продолжение идёт не дольше CONTINUE_MAX, потом снова нужно слово «Хлоя»."""
        t0 = time.time()
        self.assertEqual(self.way("хлоя включи"), "cloud")
        open_continuation(t0)
        sent, t = 0, t0
        while t < t0 + 60:
            t += 2.0   # новая фраза каждые 2 секунды
            if voice.open_until > t - 1.0 and route_phrase(Audio(2, "говорит телевизор"), t - 1.0) == "cloud":
                sent += 1
                open_continuation(t)
            else:
                break
        self.assertLessEqual(t - t0, CONTINUE_MAX + 4)
        self.assertEqual(route_phrase(Audio(2, "и дальше телевизор"), t0 + CONTINUE_MAX + 5), "skip")

    def test_stop_while_working_without_internet(self):
        busy.set()
        self.assertEqual(self.way("стоп"), "stop")
        self.assertEqual(self.way("хлоя хватит"), "stop")

    def test_while_working_long_talk_skipped_short_checked(self):
        busy.set()
        self.assertEqual(self.way("мы вчера играли в доту на инвокере и проиграли", seconds=4), "skip")
        self.assertEqual(self.way("соб", seconds=0.8), "cloud")   # офлайн-слух плохо слышит короткое «стоп»

    def test_own_echo_is_not_stop(self):
        voice.saying = "Хорошо, хватит на сегодня"
        self.assertEqual(self.way("хватит", seconds=4), "skip")

    def test_yes_no_answer_goes_through(self):
        voice.awaiting = True
        self.assertEqual(self.way("да"), "cloud")

    def test_cloud_mode_like_before(self):
        config.WAKE_OFFLINE = False
        self.assertEqual(self.way("мы играли в доту"), "cloud")

    def test_no_model_means_like_before(self):
        with mock.patch("chloe.voice.ears.hear", return_value=None):
            self.assertEqual(self.way("мы играли в доту"), "cloud")


@unittest.skipUnless(VOSK.exists() and PIPER.exists(), "нет модели Vosk или голоса Piper в ~/.chloe")
class RealModel(unittest.TestCase):
    """Настоящий Vosk на фразах, сказанных голосом Piper (модели только читаются)."""

    @classmethod
    def setUpClass(cls):
        from piper import PiperVoice

        cls.ears = Ears()
        with mock.patch("chloe.ears.EARS_DIR", VOSK.parent):
            cls.ears.load()
        cls.piper = PiperVoice.load(str(PIPER))

    def say(self, text):
        import speech_recognition as sr

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self.piper.synthesize_wav(text, w)
        buf.seek(0)
        with wave.open(buf) as w:
            data, rate = w.readframes(w.getnframes()), w.getframerate()
        return sr.AudioData(audioop.ratecv(data, 2, 1, rate, 16000, None)[0], 16000, 2)

    def test_wake_found_and_not_imagined(self):
        for text in ("Хлоя, какая погода", "сделай погромче, Хлоя", "привет Хлоя"):
            self.assertTrue(has_wake(self.ears.hear(self.say(text))), text)
        for text in ("мы вчера играли в доту на инвокере", "хлопья на завтрак", "клоун пришёл", "слоя краски"):
            self.assertFalse(has_wake(self.ears.hear(self.say(text))), text)

    def test_fast_enough(self):
        """Распознаёт быстрее, чем длится фраза, — значит, успевает за речью даже под нагрузкой."""
        audio = self.say("Хлоя, открой телеграм и напиши маме, что я задержусь")
        seconds = len(audio.frame_data) / float(audio.sample_rate * audio.sample_width)
        started = time.time()
        self.ears.hear(audio)
        self.assertLess(time.time() - started, seconds)

if __name__ == "__main__":
    unittest.main()
