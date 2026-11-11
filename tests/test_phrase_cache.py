"""Готовые короткие фразы: «Да?» звучит из файла, без сервера голоса."""
import shutil
import unittest
from unittest import mock

from chloe import phrase_cache as pc
from chloe import voice as voice_mod
from chloe.voice import Voice


class Cache(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(pc.DIR, ignore_errors=True)

    def test_short_phrase_is_kept_per_voice(self):
        self.assertIsNone(pc.get("Да?", "edge:A"))
        pc.put("Да?", "edge:A", b"ID3mp3")
        self.assertEqual(pc.get("Да?", "edge:A").read_bytes(), b"ID3mp3")
        self.assertIsNone(pc.get("Да?", "edge:B"))                  # другой голос — своя запись

    def test_long_text_is_not_cached(self):
        long = "Это длинный ответ, который не стоит хранить в готовых фразах, он каждый раз другой."
        self.assertIsNone(pc.put(long, "v", b"x"))
        self.assertIsNone(pc.get(long, "v"))

    def test_old_files_are_removed(self):
        with mock.patch.object(pc, "MAX_FILES", 2):
            for t in ("раз", "два", "три"):
                pc.put(t, "v", b"x")
        self.assertEqual(len(list(pc.DIR.glob("*.mp3"))), 2)

    def test_warm_makes_only_missing(self):
        pc.put("Да?", "v", b"x")
        made = []
        n = pc.warm("v", lambda t: made.append(t) or b"mp3", ("Да?", "Хорошо."))
        self.assertEqual((n, made), (1, ["Хорошо."]))


class Speaking(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(pc.DIR, ignore_errors=True)
        self.v = Voice(enabled=True)
        self.played = []
        self.v._play = lambda p: self.played.append(p)

    def test_first_time_from_server_then_from_file(self):
        with mock.patch.object(voice_mod, "voice_mp3", return_value=b"ID3") as server:
            self.assertTrue(self.v._say_edge("Да?"))
            self.assertTrue(self.v._say_edge("Да?"))
        server.assert_called_once()                                  # второй раз — без сервера
        self.assertEqual(len(self.played), 2)

    def test_one_off_short_answer_goes_by_stream(self):
        pc._heard.clear()
        self.assertFalse(pc.worth("Хорошо, босс, ничего не трогаю."))   # впервые — потоком, в запас не идёт
        self.assertTrue(pc.worth("Хорошо, босс, ничего не трогаю."))    # повторилась — в запас
        self.assertTrue(pc.worth("Да?"))                                 # частая — сразу

    def test_cached_phrase_plays_even_when_server_is_down(self):
        pc.put("Остановилась.", voice_mod.cache_voice(), b"ID3")
        self.v.voice_down_until = 10 ** 12
        self.assertTrue(self.v._say_edge("Остановилась."))
        self.assertEqual(len(self.played), 1)


if __name__ == "__main__":
    unittest.main()
