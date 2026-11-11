"""Голос потоком: части качаются по кусочкам и играют с первого звука. Сеть и звуковая карта подменены."""
import threading
import time
import unittest
from unittest import mock

from chloe import speech_stream as ss
RealDownload = ss.Download   # Speak подменяет Download поддельной; тест повторов берёт настоящую
from chloe import voice as voice_mod
from chloe.voice import Voice


class SlowDownload:
    """Как Download, но кусочки «приходят» сами, без сети."""
    made = []

    def __init__(self, text, voice_name, chunks=3, delay=0.05, fail=False):
        self.text, self.failed = text, fail
        self.chunks = [] if fail else [("mp3:" + text + str(i)).encode() for i in range(chunks)]
        SlowDownload.made.append(self)

    def wait_first(self):
        return not self.failed


class Speak(unittest.TestCase):
    def setUp(self):
        SlowDownload.made = []
        self.addCleanup(mock.patch.stopall)
        import pathlib
        import tempfile

        from chloe import phrase_cache                      # готовые фразы — свои в каждом тесте, без памяти о прошлых
        mock.patch.object(phrase_cache, "_heard", {}).start()
        mock.patch.object(phrase_cache, "DIR", pathlib.Path(tempfile.mkdtemp())).start()
        self.decoded = []

        def fake_feed(player, downloads):
            for d in downloads():
                if d.wait_first():
                    self.decoded.append(d.text)
                    with player.lock:
                        player.pcm += b"\1\0" * 2400   # 0,1 с звука
            player.finished = True

        mock.patch.object(ss, "Download", SlowDownload).start()
        mock.patch.object(ss.Player, "feed", fake_feed).start()

        class Device:
            def __init__(self, **kw):
                pass

            def start(self, gen):
                def pump():
                    while True:
                        try:
                            gen.send(1200)
                        except StopIteration:
                            return
                        if player_done():
                            return
                        time.sleep(0.001)
                threading.Thread(target=pump, daemon=True).start()

            def close(self):
                pass

        players = []
        orig_init = ss.Player.__init__

        def init(p, interrupt):
            orig_init(p, interrupt)
            players.append(p)
        mock.patch.object(ss.Player, "__init__", init).start()

        def player_done():
            return players and players[-1].played_all.is_set()
        import miniaudio
        mock.patch.object(miniaudio, "PlaybackDevice", Device).start()

    def test_all_parts_in_order_and_next_prefetched(self):
        parts = ["Первая часть.", "Вторая часть.", "Третья часть."]
        self.assertTrue(ss.speak(parts, "ru-RU-SvetlanaNeural", threading.Event()))
        self.assertEqual(self.decoded, parts)
        self.assertEqual([d.text for d in SlowDownload.made], parts)

    def test_no_first_sound_means_fallback_voice(self):
        mock.patch.object(ss, "Download", lambda t, v: SlowDownload(t, v, fail=True)).start()
        self.assertFalse(ss.speak(["Привет."], "ru-RU-SvetlanaNeural", threading.Event()))

    def test_voice_uses_stream_and_falls_back(self):
        v = Voice(enabled=True)
        with mock.patch.object(voice_mod, "STREAMING", True), \
             mock.patch.object(ss, "available", lambda: True), \
             mock.patch.object(ss, "speak", lambda parts, name, stop: True) as _:
            self.assertTrue(v._say_edge("Привет. Как дела?"))
        with mock.patch.object(voice_mod, "STREAMING", True), \
             mock.patch.object(ss, "available", lambda: True), \
             mock.patch.object(ss, "last_problem", "NoAudioReceived"), \
             mock.patch.object(ss, "speak", lambda parts, name, stop: False):
            self.assertFalse(v._say_edge("Привет."))          # пустой ответ сервера — запасной голос на эту фразу,
            self.assertEqual(v.voice_down_until, 0)            # но следующую Светлана попробует снова
        with mock.patch.object(voice_mod, "STREAMING", True), \
             mock.patch.object(ss, "available", lambda: True), \
             mock.patch.object(ss, "last_problem", "ClientConnectorError"), \
             mock.patch.object(ss, "speak", lambda parts, name, stop: False):
            self.assertFalse(v._say_edge("Добрый вечер."))    # нет связи — минуту не ждём Светлану зря
            # (другая фраза: повторившаяся короткая пошла бы в запас готовых фраз, а не потоком)
            self.assertGreater(v.voice_down_until, time.time())

    def test_lost_piece_is_spoken_by_sentences(self):
        """Сервер потерял кусок целиком — он придёт по предложениям, а не пропадёт молча."""
        calls = []

        class Comm:
            def __init__(self, text, voice_name, **prosody):   # скорость и высота голоса — из профиля Chloe
                self.text = text

            async def stream(self):
                calls.append(self.text)
                if "." in self.text[:-1]:                    # кусок из двух предложений сервер «теряет»
                    raise NoAudioReceived("пустой ответ")
                yield {"type": "audio", "data": self.text.encode()}

        import edge_tts
        from edge_tts.exceptions import NoAudioReceived
        with mock.patch.object(edge_tts, "Communicate", Comm), mock.patch.object(ss.time, "sleep", lambda s: None):
            d = RealDownload("Первое. Второе.", "ru-RU-SvetlanaNeural")
            while not d.done:
                time.sleep(0.01)
        self.assertEqual(bytes(d.buf), "Первое.Второе.".encode())
        self.assertEqual(calls.count("Первое. Второе."), ss.TRIES)

    def test_generator_pads_silence_and_ends(self):
        stop = threading.Event()
        p = ss.Player(stop)
        g = p.generator()
        next(g)
        with p.lock:
            p.pcm += b"\1\0" * 100
        out = g.send(200)                       # данных меньше, чем просят, — дополнено тишиной
        self.assertEqual(len(out), 400)
        self.assertFalse(p.played_all.is_set())  # ещё распаковывается — не конец
        p.finished = True
        g.send(200)
        self.assertTrue(p.played_all.is_set())


class DownloadRead(unittest.TestCase):
    def test_read_waits_for_chunks_and_ends(self):
        d = ss.Download.__new__(ss.Download)
        d.buf, d.pos, d.done, d.failed, d.cond = bytearray(), 0, False, False, threading.Condition()

        def arrive():
            for part in (b"abc", b"def"):
                time.sleep(0.05)
                with d.cond:
                    d.buf += part
                    d.cond.notify_all()
            with d.cond:
                d.done = True
                d.cond.notify_all()
        threading.Thread(target=arrive, daemon=True).start()
        self.assertTrue(d.wait_first())
        got = b""
        while True:
            c = d.read(2)
            if not c:
                break
            got += c
        self.assertEqual(got, b"abcdef")


if __name__ == "__main__":
    unittest.main()
