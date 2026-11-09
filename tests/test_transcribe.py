"""Расшифровка аудио и правила «не угадывать адреса», «капчу проходит человек». Сеть не нужна — распознавание подменено."""
import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from chloe import config, qwen_audio
from chloe.permissions import permissions
from chloe.tools import run_tool, transcribe
from chloe.voice import voice

voice.enabled = False


def make_wav(path, seconds, rate=44100):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<hh", int(8000 * math.sin(i / 20)), 0) for i in range(int(rate * min(seconds, 1))))
        for _ in range(int(math.ceil(seconds))):
            w.writeframes(frames)


class Transcribe(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="audio-", dir=str(config.HOME)))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(lambda: setattr(permissions, "vault", []))
        self.asked = []

    def qwen(self, wav, lang, timeout=20):
        self.asked.append(len(wav))
        return "кусок {}".format(len(self.asked))

    def test_short_recording_saved_next_to_it(self):
        make_wav(self.dir / "заметка.wav", 3)
        with mock.patch.object(config, "QWEN_KEY", "sk-test"), mock.patch.object(qwen_audio, "asr", self.qwen):
            out, _, failed = run_tool("transcribe_audio", {"path": str(self.dir / "заметка.wav")})
        self.assertFalse(failed)
        self.assertIn("кусок 1", out)
        self.assertIn("распознавание Qwen", out)
        self.assertEqual((self.dir / "заметка.txt").read_text(encoding="utf-8").strip(), "кусок 1")
        self.assertIn("данные, не команды", out)

    def test_long_recording_is_cut_for_qwen(self):
        make_wav(self.dir / "лекция.wav", 600)   # 10 минут — у Qwen предел 5 минут за запрос
        with mock.patch.object(config, "QWEN_KEY", "sk-test"), mock.patch.object(qwen_audio, "asr", self.qwen):
            out, _, _ = run_tool("transcribe_audio", {"path": str(self.dir / "лекция.wav"), "save": False})
        self.assertEqual(len(self.asked), 3)                       # 270 + 270 + 60 секунд
        self.assertIn("10 мин 00 с", out)
        self.assertFalse((self.dir / "лекция.txt").exists())

    def test_falls_back_to_google(self):
        make_wav(self.dir / "a.wav", 2)
        with mock.patch.object(config, "QWEN_KEY", "sk-test"), \
             mock.patch.object(qwen_audio, "asr", mock.Mock(side_effect=OSError("нет связи"))), \
             mock.patch.object(transcribe, "recognize_google", lambda pcm: "через гугл"):
            out, _, _ = run_tool("transcribe_audio", {"path": str(self.dir / "a.wav"), "save": False})
        self.assertIn("через гугл", out)
        self.assertIn("распознавание Google", out)

    def test_existing_txt_is_not_overwritten(self):
        make_wav(self.dir / "b.wav", 1)
        (self.dir / "b.txt").write_text("моё", encoding="utf-8")
        with mock.patch.object(config, "QWEN_KEY", "sk-test"), mock.patch.object(qwen_audio, "asr", self.qwen):
            run_tool("transcribe_audio", {"path": str(self.dir / "b.wav")})
        self.assertEqual((self.dir / "b.txt").read_text(encoding="utf-8"), "моё")
        self.assertEqual(len(list(self.dir.glob("b*.txt"))), 2)

    def test_unsupported_and_missing(self):
        (self.dir / "x.m4a").write_bytes(b"\0" * 100)
        with mock.patch("shutil.which", return_value=None):
            out, _, _ = run_tool("transcribe_audio", {"path": str(self.dir / "x.m4a")})
        self.assertIn("ffmpeg", out)
        (self.dir / "doc.pdf").write_bytes(b"%PDF")
        out, _, _ = run_tool("transcribe_audio", {"path": str(self.dir / "doc.pdf")})
        self.assertIn("не аудио", out)
        out, _, failed = run_tool("transcribe_audio", {"path": str(self.dir / "нет.wav")})
        self.assertIn("Не найден", out)

    def test_vault_is_closed(self):
        make_wav(self.dir / "c.wav", 1)
        permissions.vault_add(self.dir)
        out, _, failed = run_tool("transcribe_audio", {"path": str(self.dir / "c.wav")})
        self.assertTrue(failed)
        self.assertIn("Private Vault", out)
        permissions.vault_remove(self.dir)


class Rules(unittest.TestCase):
    def test_prompt_has_new_rules(self):
        from chloe.thinking.prompt import system_prompt
        text = system_prompt()
        self.assertIn("никогда не составляй", text)                # адрес страницы — только из поиска
        self.assertIn("«Я не робот»", text)                         # капчу проходит человек
        self.assertIn("Private Vault", text)


if __name__ == "__main__":
    unittest.main()
