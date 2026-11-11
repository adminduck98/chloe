"""Слух и перебивание: «стоп» останавливает речь и задачу, свой голос не принимается за команду,
части фразы, сказанные с паузами, склеиваются."""
import threading
import time
import types
import unittest
from unittest import mock

from chloe import config, signals, voice as voice_mod
from chloe.signals import audio_q, busy, drain, heard_q, interrupt, is_stop
from chloe.thinking import think
from chloe.tools import HANDLERS
from chloe.voice import finish_speech, listener, voice

voice.enabled = False


def block(**kw):
    return types.SimpleNamespace(**kw)


class FakeClaude:
    """Каждый ответ просит два инструмента."""
    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        return block(stop_reason="tool_use", content=[
            block(type="tool_use", id="a%d" % self.calls, name="system_info", input={}),
            block(type="tool_use", id="b%d" % self.calls, name="list_folder", input={"path": "~"}),
        ])


class StopTest(unittest.TestCase):
    def test_stop_words(self):
        for text in ("стоп", "Хлоя, хватит", "замолчи"):
            self.assertTrue(is_stop(text), text)
        for text in ("стоп машина едет быстро", "открой браузер"):
            self.assertFalse(is_stop(text), text)

    def test_stop_in_the_middle_of_a_task(self):
        fake = FakeClaude()
        real = HANDLERS["system_info"]

        def info(a):
            if fake.calls == 2:   # «стоп» посреди второго шага
                interrupt.set()
            return real(a)

        HANDLERS["system_info"] = info
        config.PROVIDER = "anthropic"
        try:
            interrupt.clear()
            msgs = []
            self.assertIsNone(think(fake, msgs, "сделай много шагов"))
        finally:
            HANDLERS["system_info"] = real
            interrupt.clear()
        self.assertEqual(fake.calls, 2)
        self.assertIn("стоп", msgs[-2]["content"][1]["content"])   # второй инструмент не выполнен
        self.assertEqual(msgs[-1]["content"][0]["text"], signals.STOPPED)
        # у каждого запроса инструмента есть ответ — следующая просьба не сломается
        asked = {b.id for m in msgs if m["role"] == "assistant" and not isinstance(m["content"][0], dict) for b in m["content"]}
        answered = {r["tool_use_id"] for m in msgs if m["role"] == "user" for r in m["content"] if r.get("type") == "tool_result"}
        self.assertEqual(asked, answered)


class ListenerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        voice.recognize = lambda audio: audio   # «запись» сразу текст
        threading.Thread(target=listener, daemon=True).start()

    def hear(self, text, busy_now=False, saying="", spoke_ago=None, started_ago=0.0):
        interrupt.clear()
        drain(heard_q)
        (busy.set if busy_now else busy.clear)()
        voice.saying = saying
        voice.spoke_until = time.time() - spoke_ago if spoke_ago is not None else 0
        audio_q.put((text, time.time() - started_ago))
        time.sleep(0.3)
        result = interrupt.is_set(), heard_q.qsize() > 0
        busy.clear()
        voice.saying = ""
        return result

    def test_phrase_keeps_when_it_was_started(self):
        # окно «без Хлоя» проверяется по началу речи: медленное распознавание не должно его закрывать
        with mock.patch("chloe.voice.route_phrase", lambda audio, started: "cloud"):
            self.hear("ну ты всё равно не так хорошо", started_ago=5.0)
            got = heard_q.get(timeout=1)
        self.assertEqual(got, "ну ты всё равно не так хорошо")
        self.assertAlmostEqual(got.started, time.time() - 5.0, delta=1.0)

    def test_cases(self):
        self.assertEqual(self.hear("стоп", busy_now=True), (True, False))
        self.assertEqual(self.hear("открой браузер", busy_now=True), (False, False))
        self.assertEqual(self.hear("хватит", saying="Хорошо, хватит на сегодня"), (False, False))   # эхо её слов
        self.assertEqual(self.hear("стоп", saying="Сейчас открою браузер"), (True, False))
        self.assertEqual(self.hear("Хлоя, открой браузер"), (False, True))
        self.assertEqual(self.hear("открой браузер", spoke_ago=1.0, started_ago=0.5), (False, True))   # быстрый ответ после неё
        self.assertEqual(self.hear("открой браузер", spoke_ago=0.5, started_ago=1.5), (False, False))  # началось, пока она говорила


class FinishSpeechTest(unittest.TestCase):
    def run_script(self, script, start="открой папку"):
        drain(heard_q)
        voice.last_loud = time.time() - 0.2

        def feed():
            for delay, kind, value in script:
                time.sleep(delay)
                if kind == "loud":
                    voice.last_loud = time.time()
                else:
                    heard_q.put(value)

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        began = time.time()
        result = finish_speech(start)
        self.elapsed = time.time() - began
        feeder.join()   # опоздавшая часть не должна попасть в следующий тест
        drain(heard_q)
        return result

    def test_pauses_are_joined(self):
        self.assertEqual(self.run_script([]), "открой папку")
        self.assertEqual(self.run_script([(1.0, "loud", 0), (0.5, "loud", 0), (0.6, "text", "Документы")]),
                         "открой папку Документы")

    def test_long_speech_waits_longer_at_a_pause(self):
        # длинная диктовка: человек замолчал на 1,9 с, задумавшись, — это ещё не конец (короткой команде хватило бы 1,5 с)
        long = "напиши письмо Ахмеду что я задержусь на час потому что"
        self.assertEqual(self.run_script([(1.9, "text", "пробки на дороге")], start=long), long + " пробки на дороге")

    def test_short_command_still_ends_quickly(self):
        started = time.time()
        self.assertEqual(self.run_script([]), "открой папку")
        self.assertLess(time.time() - started, 1.8)

    def test_music_does_not_hold_the_phrase(self):
        # играет музыка: микрофон всё время «громкий», но слов не прибавляется — дослушивание не тянется минуту
        from chloe import voice as vm
        script = [(0.4, "loud", 0)] * 20
        with mock.patch.object(vm, "NO_NEW_WORDS", 2.0):
            self.assertEqual(self.run_script(script), "открой папку")
            self.assertLess(self.elapsed, 3.0)

    def test_long_silence_ends_the_phrase(self):
        self.assertEqual(self.run_script([(3.0, "loud", 0), (0.3, "text", "спасибо")]), "открой папку")
        drain(heard_q)


assert voice_mod.voice is voice

if __name__ == "__main__":
    unittest.main()
