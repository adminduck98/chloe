"""Голос и слух Qwen: разбор ответов сервера и запасные варианты (Светлана, Google). Сеть не нужна — всё подменено."""
import base64
import io
import json
import unittest
from unittest import mock

from chloe import config, qwen_audio, speech_stream as ss
from chloe import voice as voice_mod
from chloe.voice import Voice


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def sse(*chunks):
    lines = ["data:" + json.dumps({"output": {"audio": {"data": base64.b64encode(c).decode()}}}) for c in chunks]
    return FakeResponse(("\n".join(lines) + "\n").encode())


class QwenAudio(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(config, "QWEN_KEY", "sk-sp-test").start()
        mock.patch.object(qwen_audio, "native_base", lambda: "https://token-plan.example").start()

    def test_tts_stream_joins_sse_chunks(self):
        sent = []

        def urlopen(req, timeout=None):
            sent.append((req.full_url, req.headers.get("X-dashscope-sse"), json.loads(req.data)))
            return sse(b"ID3", b"mp3-1", b"mp3-2")

        with mock.patch("urllib.request.urlopen", urlopen):
            self.assertEqual(qwen_audio.tts_mp3("Привет"), b"ID3mp3-1mp3-2")
        url, sse_header, body = sent[0]
        self.assertTrue(url.endswith("/api/v1/services/audio/tts/SpeechSynthesizer"))
        self.assertEqual(sse_header, "enable")
        self.assertEqual(body["input"]["voice"], qwen_audio.VOICE)
        self.assertEqual(body["input"]["format"], "mp3")

    def test_asr_reads_text(self):
        resp = FakeResponse(json.dumps({"output": {"text": "открой брейв"}}).encode())
        with mock.patch("urllib.request.urlopen", lambda req, timeout=None: resp):
            self.assertEqual(qwen_audio.asr(b"RIFF....", "ru"), "открой брейв")

    def test_asr_reads_chat_style_answer(self):
        resp = FakeResponse(json.dumps({"output": {"choices": [{"message": {"content": [{"text": "привет"}]}}]}}).encode())
        with mock.patch("urllib.request.urlopen", lambda req, timeout=None: resp):
            self.assertEqual(qwen_audio.asr(b"RIFF....", "ru"), "привет")

    def test_recognize_uses_qwen_then_google_on_failure(self):
        v = Voice(enabled=True)
        v.recognizer = mock.Mock()
        v.recognizer.recognize_google.return_value = "через гугл"
        audio = mock.Mock()
        audio.get_wav_data.return_value = b"RIFF"
        with mock.patch.object(config, "ASR", "qwen"), mock.patch.object(qwen_audio, "asr", lambda wav, lang: "через квен"):
            self.assertEqual(v.recognize(audio), "через квен")
        with mock.patch.object(config, "ASR", "qwen"), \
             mock.patch.object(qwen_audio, "asr", mock.Mock(side_effect=OSError("нет связи"))):
            self.assertEqual(v.recognize(audio), "через гугл")
            self.assertGreater(v.asr_down_until, 0)                # минуту Qwen не дёргаем зря
            self.assertEqual(v.recognize(audio), "через гугл")

    def test_fragment_or_silence_is_not_a_breakdown(self):
        # Qwen отвечает «400 {}» на обрывок короче ~0,3 с и на тишину: это «речи нет», а не поломка
        v = Voice(enabled=True)
        v.recognizer = mock.Mock()
        v.recognizer.recognize_google.return_value = "да"
        audio = mock.Mock()
        audio.get_wav_data.return_value = b"RIFF"
        with mock.patch.object(config, "ASR", "qwen"), \
             mock.patch("urllib.request.urlopen", mock.Mock(side_effect=__import__("urllib.error").error.HTTPError(
                 "u", 400, "Bad Request", {}, io.BytesIO(b"{}")))):
            self.assertEqual(v.recognize(audio), "да")               # Google что-то услышал — берём
        self.assertEqual(v.asr_down_until, 0)                        # и Qwen не выключаем на минуту

    def test_empty_qwen_answer_uses_google(self):
        v = Voice(enabled=True)
        v.recognizer = mock.Mock()
        v.recognizer.recognize_google.return_value = "стоп"
        audio = mock.Mock()
        audio.get_wav_data.return_value = b"RIFF"
        with mock.patch.object(config, "ASR", "qwen"), mock.patch.object(qwen_audio, "asr", lambda wav, lang: ""):
            self.assertEqual(v.recognize(audio), "стоп")

    def test_slow_qwen_loses_the_race_to_google(self):
        import time
        v = Voice(enabled=True)
        v.recognizer = mock.Mock()
        v.recognizer.recognize_google.return_value = "через гугл"
        audio = mock.Mock()
        audio.get_wav_data.return_value = b"RIFF"
        with mock.patch.object(config, "ASR", "qwen"), mock.patch.object(voice_mod, "QWEN_ASR_WAIT", 0.3), \
             mock.patch.object(qwen_audio, "asr", lambda wav, lang: time.sleep(1.5) or "поздно"):
            started = time.time()
            self.assertEqual(v.recognize(audio), "через гугл")
            self.assertLess(time.time() - started, 1.0)              # не ждём медленный Qwen
        self.assertEqual(v.asr_down_until, 0)                        # медленный — не значит сломанный

    def test_qwen_voice_falls_back_to_svetlana(self):
        v = Voice(enabled=True)
        calls = []
        with mock.patch.object(voice_mod, "TTS", "qwen"), \
             mock.patch.object(v, "_say_qwen", lambda t: calls.append("qwen") or False), \
             mock.patch.object(v, "_say_edge", lambda t: calls.append("edge") or True), \
             mock.patch.object(v, "_say_pyttsx3", lambda t: calls.append("system")):
            v.say("Привет")
        self.assertEqual(calls, ["qwen", "edge"])                   # робот-голос не включается

    def test_qwen_download_streams_into_player(self):
        with mock.patch.object(qwen_audio, "tts_stream", lambda text, voice=None, timeout=30: iter([b"ab", b"cd"])):
            d = ss.QwenDownload("Привет.", "longanlingxin")
            self.assertTrue(d.wait_first())
            while not d.done:
                pass
        self.assertEqual(bytes(d.buf), b"abcd")
        self.assertFalse(d.failed)

    def test_qwen_download_failure_is_reported(self):
        def broken(text, voice=None, timeout=30):
            raise RuntimeError("кредиты кончились")
            yield b""

        with mock.patch.object(qwen_audio, "tts_stream", broken):
            d = ss.QwenDownload("Привет.", "longanlingxin")
            self.assertFalse(d.wait_first())
        self.assertTrue(d.failed)

    def test_no_key_means_google_and_svetlana(self):
        with mock.patch.object(config, "QWEN_KEY", None):
            self.assertFalse(qwen_audio.available())
            self.assertFalse(Voice(enabled=True)._say_qwen("Привет"))


if __name__ == "__main__":
    unittest.main()
