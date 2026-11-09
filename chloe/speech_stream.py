"""Голос без ожидания: Светлана начинает говорить с первого кусочка звука, а не после всей фразы.

Сервер Microsoft (edge-tts) присылает mp3 кусочками; бывает, что вся фраза идёт 10–30 секунд, а первый звук —
через 1–4. Здесь кусочки сразу распаковываются (miniaudio) и играют; следующая часть ответа загружается,
пока звучит текущая. Нет miniaudio — voice.py говорит по-старому (целым файлом).
"""
import asyncio
import re
import threading
import time

RATE, CHANNELS = 24000, 1            # edge-tts: audio-24khz-48kbitrate-mono-mp3
BYTES_PER_SECOND = RATE * CHANNELS * 2
START_AFTER = 0.3                     # секунды звука в запасе, прежде чем начать играть
# Сервер Microsoft иногда (до половины запросов подряд) отвечает без звука — NoAudioReceived. Текст тут ни при чём:
# та же фраза следующим запросом проходит. Поэтому: больше попыток, а не дошедшая часть — по предложениям.
TRIES = 5
last_problem = None                   # почему последняя часть не пришла: имя ошибки (для voice.py)


def sentences(text):
    return [p for p in re.split(r"(?<=[.!?…])\s+", text.strip()) if p]


def no_connection(problem_name):
    """Нет связи с сервером — а не случайный пустой ответ: только тогда голос считаем недоступным."""
    return problem_name not in (None, "NoAudioReceived", "TimeoutError")


def available():
    import importlib.util

    return all(importlib.util.find_spec(m) is not None for m in ("miniaudio", "edge_tts"))


class Download:
    """mp3 одной части ответа: качается в своём потоке, читается по мере прихода."""

    def __init__(self, text, voice_name, timeout=60, tries=TRIES):
        self.text, self.voice_name, self.timeout, self.tries = text, voice_name, timeout, tries
        self.buf = bytearray()
        self.pos = 0
        self.done = False
        self.failed = False
        self.cond = threading.Condition()
        threading.Thread(target=self._run, daemon=True, name="voice-download").start()

    def _run(self):
        import edge_tts

        async def go(text):
            async for chunk in edge_tts.Communicate(text, self.voice_name).stream():
                if chunk["type"] == "audio":
                    with self.cond:
                        self.buf += chunk["data"]
                        self.cond.notify_all()

        def attempt(text, tries):
            problem = None
            for _ in range(tries):
                started = time.time()
                try:
                    asyncio.run(asyncio.wait_for(go(text), self.timeout))
                    return None
                except Exception as e:
                    problem = e
                    with self.cond:
                        got = len(self.buf)
                    if got > before:
                        return problem   # часть уже звучит — повтор начал бы фразу заново; доиграем, что пришло
                    if time.time() - started < 3 and no_connection(type(e).__name__):
                        time.sleep(1)   # отказ сразу — нет связи; секунда и ещё раз
            return problem

        before = 0
        problem = attempt(self.text, self.tries)
        parts = sentences(self.text)
        if problem is not None and not self.buf and len(parts) > 1 and not no_connection(type(problem).__name__):
            # целиком не пришла — по предложениям: короткие запросы сервер теряет реже, и пропадёт не весь кусок
            problem = None
            for sentence in parts:
                with self.cond:
                    before = len(self.buf)
                p = attempt(sentence, 3)
                problem = problem or p
        global last_problem
        last_problem = type(problem).__name__ if problem is not None and not self.buf else None
        with self.cond:
            self.failed = problem is not None and not self.buf
            self.done = True
            self.cond.notify_all()
        if problem is not None:
            print("[голос: {} — {}]".format("не ответил" if self.failed else "оборвался", type(problem).__name__))

    def read(self, n):
        """До n байт; ждёт, пока придут. b"" — конец."""
        with self.cond:
            while self.pos >= len(self.buf) and not self.done:
                self.cond.wait(0.5)
            chunk = bytes(self.buf[self.pos:self.pos + n])
            self.pos += len(chunk)
            return chunk

    def wait_first(self):
        """Ждёт первый звук. False — части не будет (Светлана недоступна)."""
        with self.cond:
            while not self.buf and not self.done:
                self.cond.wait(0.5)
            return bool(self.buf)


class QwenDownload(Download):
    """То же, что Download, но голосом Qwen: mp3 приходит кусочками по SSE, первый звук ~1 с."""

    def _run(self):
        from . import qwen_audio

        problem = None
        for _ in range(2):
            try:
                for chunk in qwen_audio.tts_stream(self.text, self.voice_name, timeout=self.timeout):
                    with self.cond:
                        self.buf += chunk
                        self.cond.notify_all()
                problem = None
                break
            except Exception as e:
                problem = e
                with self.cond:
                    if self.buf:
                        break   # часть уже звучит — повтор начал бы фразу заново
        global last_problem
        last_problem = type(problem).__name__ if problem is not None and not self.buf else None
        with self.cond:
            self.failed = problem is not None and not self.buf
            self.done = True
            self.cond.notify_all()
        if problem is not None:
            print("[голос Qwen: {} — {}]".format("не ответил" if self.failed else "оборвался", str(problem)[:80]))


def make_source(download):
    import miniaudio

    class Source(miniaudio.StreamableSource):
        def read(self, num_bytes):
            return download.read(num_bytes)

    return Source()


class Player:
    """Распаковывает части по очереди в один поток PCM и играет его; «стоп» обрывает сразу."""

    def __init__(self, interrupt):
        self.interrupt = interrupt
        self.pcm = bytearray()
        self.lock = threading.Lock()
        self.finished = False      # всё распаковано
        self.played_all = threading.Event()

    def feed(self, downloads):
        import miniaudio

        try:
            for d in downloads():
                if self.interrupt.is_set():
                    break
                if not d.wait_first():
                    continue
                for frames in miniaudio.stream_any(make_source(d), source_format=miniaudio.FileFormat.MP3,
                                                   output_format=miniaudio.SampleFormat.SIGNED16,
                                                   nchannels=CHANNELS, sample_rate=RATE):
                    with self.lock:
                        self.pcm += frames.tobytes()
                    if self.interrupt.is_set():
                        break
        except Exception as e:
            print("[голос: распаковка — " + str(e)[:80] + "]")
        finally:
            self.finished = True

    def generator(self):
        required = yield b""
        while True:
            need = required * CHANNELS * 2
            with self.lock:
                chunk = bytes(self.pcm[:need])
                del self.pcm[:need]
                empty = not self.pcm
            if self.interrupt.is_set() or (self.finished and empty and len(chunk) < need):
                self.played_all.set()
                required = yield chunk + b"\0" * (need - len(chunk))
                continue
            required = yield chunk + b"\0" * (need - len(chunk))   # не успело прийти — короткая тишина

    def buffered(self):
        with self.lock:
            return len(self.pcm) / BYTES_PER_SECOND


def speak(parts, voice_name, interrupt, make=None):
    """Говорит части ответа потоком. True — сказано (или прервано «стоп»); False — первая часть не пришла,
    пусть говорит запасной голос."""
    import miniaudio

    if not parts:
        return True
    make = make or Download   # по умолчанию — Светлана (edge-tts); голос Qwen передаёт QwenDownload
    downloads = [make(parts[0], voice_name)]
    if not downloads[0].wait_first():
        return False

    def ordered():
        for i in range(len(parts)):
            if i + 1 < len(parts) and len(downloads) == i + 1:
                downloads.append(make(parts[i + 1], voice_name))   # следующая качается, пока звучит эта
            yield downloads[i]

    player = Player(interrupt)
    threading.Thread(target=player.feed, args=(ordered,), daemon=True, name="voice-decode").start()
    deadline = time.time() + 15
    while player.buffered() < START_AFTER and not player.finished and time.time() < deadline and not interrupt.is_set():
        time.sleep(0.02)
    gen = player.generator()
    next(gen)
    device = miniaudio.PlaybackDevice(output_format=miniaudio.SampleFormat.SIGNED16, nchannels=CHANNELS,
                                      sample_rate=RATE, buffersize_msec=150, app_name="Chloe")
    try:
        device.start(gen)
        while not player.played_all.wait(0.05):
            pass
        time.sleep(0.15)   # доиграть то, что уже в звуковой карте
    finally:
        device.close()
    return True
