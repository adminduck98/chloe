"""Голос: порядок движков озвучки и запасные варианты."""
import unittest
from unittest import mock

from chloe import voice as voice_mod
from chloe.voice import Voice


class Engines(unittest.TestCase):
    def setUp(self):
        self.v = Voice(enabled=True)
        self.calls = []

    def fake(self, name, ok):
        def engine(text):
            self.calls.append(name)
            return ok
        return engine

    def say(self, piper_ok, edge_ok, tts="edge"):
        with mock.patch.object(voice_mod, "TTS", tts), \
             mock.patch.object(self.v, "_say_piper", self.fake("piper", piper_ok)), \
             mock.patch.object(self.v, "_say_edge", self.fake("edge", edge_ok)), \
             mock.patch.object(self.v, "_say_pyttsx3", self.fake("system", True)):
            self.v.say("Привет")
        return self.calls

    def test_online_voice_by_default(self):
        self.assertEqual(self.say(True, True), ["edge"])   # Светлана — и больше ничего

    def test_piper_only_when_online_voice_silent(self):
        self.assertEqual(self.say(True, False), ["edge", "piper"])   # женский офлайн-голос, а не робот

    def test_system_voice_last(self):
        self.assertEqual(self.say(False, False), ["edge", "piper", "system"])

    def test_piper_first_if_chosen(self):
        self.assertEqual(self.say(True, True, tts="piper"), ["piper"])

    def test_svetlana_only_has_no_backups(self):
        self.assertEqual(self.say(True, True, tts="svetlana"), ["edge"])
        self.calls.clear()
        self.assertEqual(self.say(True, False, tts="svetlana"), ["edge"])   # без интернета молчит: ни Ирины, ни робота

    def test_missing_model_is_not_an_error(self):
        # в тестовой домашней папке модели Piper нет: голос просто уступает место следующему
        self.assertIsNone(self.v.load_piper())
        self.assertFalse(self.v._say_piper("Привет"))


class OnlineVoice(unittest.TestCase):
    """Светлана говорит везде: и длинные ответы (поиск), и на телефоне. Сеть не нужна — voice_mp3 подменён."""

    def setUp(self):
        self.v = Voice(enabled=True)
        self.played, self.asked, self.piper = [], [], []
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(self.v, "_play", lambda path: self.played.append(path)).start()
        mock.patch.object(self.v, "_say_piper", lambda t: self.piper.append(t) or True).start()

    def ava(self, fail_on=()):
        def fake(text, **kw):
            self.asked.append(text)
            return None if len(self.asked) in fail_on else b"mp3:" + text.encode()
        mock.patch.object(voice_mod, "voice_mp3", fake).start()

    def test_pieces_keep_text_and_size(self):
        text = "Первое предложение. " * 40 + "Очень " * 120 + "длинное без точек"
        parts = voice_mod.pieces(text)
        self.assertTrue(all(len(p) <= 300 for p in parts))
        self.assertEqual(" ".join(parts).split(), text.split())
        self.assertEqual(voice_mod.pieces("Коротко."), ["Коротко."])

    def test_long_search_answer_is_all_ava(self):
        self.ava()
        text = "Нашла в интернете. " + "Курс доллара сегодня такой-то, по данным банка. " * 30
        self.assertTrue(self.v._say_edge(text))
        self.assertGreater(len(self.asked), 1)                 # частями, а не одним куском до таймаута
        self.assertEqual(len(self.played), len(self.asked))
        self.assertEqual(self.piper, [])                       # запасной голос не звучал

    def test_offline_falls_back_and_retries_later(self):
        self.ava(fail_on=(1,))
        self.assertFalse(self.v._say_edge("Привет."))          # первая часть не озвучилась — запасной голос
        self.assertFalse(self.v._say_edge("Ещё раз."))         # минуту не ждём Светлану зря
        self.assertEqual(len(self.asked), 1)
        self.v.voice_down_until = 0
        self.assertTrue(self.v._say_edge("Интернет вернулся."))

    def test_phone_gets_ava(self):
        import base64

        from chloe import remote
        from chloe.app import Api

        self.assertIn("tts", remote.ALLOWED)
        with mock.patch.object(voice_mod, "voice_mp3", lambda t, **kw: b"mp3"):
            self.assertEqual(base64.b64decode(Api().tts("Привет")["audio"]), b"mp3")
        with mock.patch.object(voice_mod, "voice_mp3", lambda t, **kw: None):
            self.assertIn("error", Api().tts("Привет"))



class SpokenText(unittest.TestCase):
    def test_markdown_removed_for_speech(self):
        from chloe.voice import spoken

        out = spoken("Проверила, босс.\n\n**Состояние кода:** всё чисто.\n- первое\n- второе\n[ссылка](https://x.ru) и `код`\n## Итог")
        for mark in ("**", "`", "##", "](", "- "):
            self.assertNotIn(mark, out)
        self.assertIn("Состояние кода: всё чисто.", out)
        self.assertIn("ссылка и код", out)
        self.assertEqual(spoken("Обычный текст, без разметки: 2 * 3 = 6."), "Обычный текст, без разметки: 2 3 = 6.")


if __name__ == "__main__":
    unittest.main()
