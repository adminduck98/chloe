"""Слух GigaAM: разбор WAV, обрывки, выбор слуха в Voice.recognize и запасной путь при сбое. Модель не нужна — подменена."""
import io
import unittest
import wave
from unittest import mock

import numpy as np

from chloe import config, gigaam, qwen_audio
from chloe.voice import Voice


def wav(seconds=1.0, rate=16000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        t = np.arange(n) / rate
        x = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
        w.writeframes(np.repeat(x, channels).tobytes())
    return buf.getvalue()


class FakeAudio:
    def __init__(self, seconds=1.0):
        self.data = wav(seconds)

    def get_wav_data(self, convert_rate=None, convert_width=None):
        return self.data


class FakeStream:
    def __init__(self):
        self.got = None
        self.result = mock.Mock(text="  Хлоя, включи свет.  ")

    def accept_waveform(self, rate, a):
        self.got = (rate, a)


class FakeRec:
    def __init__(self):
        self.streams = []

    def create_stream(self):
        s = FakeStream()
        self.streams.append(s)
        return s

    def decode_stream(self, s):
        pass


class Samples(unittest.TestCase):
    def test_mono_16bit(self):
        rate, a = gigaam.samples(wav(0.5))
        self.assertEqual(rate, 16000)
        self.assertEqual(a.dtype, np.float32)
        self.assertEqual(len(a), 8000)
        self.assertLessEqual(float(np.abs(a).max()), 1.0)

    def test_stereo_is_mixed_down(self):
        rate, a = gigaam.samples(wav(0.5, channels=2))
        self.assertEqual(len(a), 8000)


class Asr(unittest.TestCase):
    def setUp(self):
        self.rec = FakeRec()
        p = mock.patch.object(gigaam, "_recognizer", return_value=self.rec)
        p.start()
        self.addCleanup(p.stop)

    def test_text_is_trimmed(self):
        self.assertEqual(gigaam.asr(wav(1.0)), "Хлоя, включи свет.")
        rate, a = self.rec.streams[0].got
        self.assertEqual(rate, 16000)

    def test_scrap_shorter_than_quarter_second_is_not_speech(self):
        self.assertEqual(gigaam.asr(wav(0.1)), "")
        self.assertEqual(self.rec.streams, [])


class Recognize(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch("chloe.voice.brain").start()
        self.v = Voice.__new__(Voice)
        self.v.asr_down_until = 0
        self.v.last_said = ""
        self.v.recognizer = mock.Mock()

    def test_gigaam_first_no_network(self):
        mock.patch.object(config, "ASR", "gigaam").start()
        mock.patch.object(gigaam, "available", return_value=True).start()
        mock.patch.object(gigaam, "asr", return_value="привет").start()
        qasr = mock.patch.object(qwen_audio, "asr").start()
        self.assertEqual(self.v.recognize(FakeAudio()), "привет")
        qasr.assert_not_called()
        self.v.recognizer.recognize_google.assert_not_called()

    def test_gigaam_failure_falls_back(self):
        mock.patch.object(config, "ASR", "gigaam").start()
        mock.patch.object(gigaam, "available", return_value=True).start()
        mock.patch.object(gigaam, "asr", side_effect=RuntimeError("boom")).start()
        mock.patch.object(qwen_audio, "available", return_value=False).start()
        self.v.recognizer.recognize_google.return_value = "запасной"
        self.assertEqual(self.v.recognize(FakeAudio()), "запасной")

    def test_model_missing_uses_old_path(self):
        mock.patch.object(config, "ASR", "gigaam").start()
        mock.patch.object(gigaam, "available", return_value=False).start()
        g = mock.patch.object(gigaam, "asr").start()
        mock.patch.object(qwen_audio, "available", return_value=False).start()
        self.v.recognizer.recognize_google.return_value = "гугл"
        self.assertEqual(self.v.recognize(FakeAudio()), "гугл")
        g.assert_not_called()


if __name__ == "__main__":
    unittest.main()
