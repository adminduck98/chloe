"""Слух и голос. Микрофон открыт всё время (поток записи), фразы распознаются параллельно (поток слуха),
Chloe дослушивает до конца, говорит естественным голосом и замолкает на «стоп»."""
import asyncio
import contextlib
import os
import queue
import re
import tempfile
import threading
import time
import wave
import warnings

with warnings.catch_warnings():   # audioop помечен устаревшим, но им же пользуется speech_recognition
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

from . import config, speech_stream
from .brain import brain
from .ears import ears, has_wake
from .config import DATA, LANG, NO_WORDS, PAUSE, PHRASE_LIMIT, PIPER_VOICE, STOP_WORDS, TTS, VOICES, VOICES_DIR, YES_WORDS
from .journal import journal
from .secret import redact
from .signals import audio_q, busy, commands, drain, heard_q, interrupt, is_stop, state, words


@contextlib.contextmanager
def native_quiet():
    """Глушит сообщения ALSA и JACK, которые PyAudio печатает в stderr при каждом открытии микрофона."""
    try:
        saved, null = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    except OSError:
        yield
        return
    os.dup2(null, 2)
    try:
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(null)


STREAMING = os.environ.get("CHLOE_STREAM_VOICE", "on") != "off"   # говорить с первого кусочка звука


class Voice:
    """Слух (распознавание речи) и голос (озвучка)."""

    def __init__(self, enabled):
        self.enabled = enabled
        self.recognizer = None
        self.mic = None
        self.tts_engine = None
        self.mixer_ready = False
        self.saying = ""          # что Chloe говорит прямо сейчас
        self.spoke_until = 0.0    # когда она закончила говорить
        self.awaiting = False     # ждёт ответа «да/нет»
        self.voice_down_until = 0.0  # Светлана не ответила (нет интернета) — до этого времени сразу запасной голос
        self.piper = None         # офлайн-голос, загружается один раз
        self.piper_failed = False
        self.piper_lock = threading.Lock()
        self.last_loud = 0.0      # когда в микрофоне последний раз был голос
        self.recognizing = False  # фраза сейчас распознаётся
        self.open_until = 0.0     # до этого времени части начатой просьбы идут на распознавание без слова «Хлоя»
        self.open_origin = 0.0    # когда началась эта просьба
        self.reason = ""          # почему последняя фраза ушла на распознавание

    # --- слух ---
    @contextlib.contextmanager
    def _open_mic(self):
        with native_quiet():
            source = self.mic.__enter__()
        try:
            yield source
        finally:
            self.mic.__exit__(None, None, None)

    def setup_mic(self):
        import speech_recognition as sr

        if self.recognizer is None:
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = True
            # части фразы режутся по короткой паузе, чтобы распознавание начиналось сразу;
            # дослушивает до конца finish_speech — ждёт тишины дольше PAUSE
            self.recognizer.pause_threshold = min(PAUSE, 0.8)
            with native_quiet():
                self.mic = sr.Microphone()
            with self._open_mic() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.8)

    def record(self):
        """Микрофон открыт всё время: пока одна фраза распознаётся, следующая уже записывается — ничего не теряется."""
        import speech_recognition as sr

        self.setup_mic()
        with self._open_mic() as source:
            # следим за громкостью каждого кусочка звука: так видно, что человек ещё говорит,
            # даже если библиотека уже отдала первую часть фразы
            raw_read = source.stream.read

            def read(size):
                data = raw_read(size)
                try:
                    if audioop.rms(data, source.SAMPLE_WIDTH) > self.recognizer.energy_threshold:
                        self.last_loud = time.time()
                except Exception:
                    pass
                return data

            source.stream.read = read
            while True:
                try:
                    audio = self.recognizer.listen(source, timeout=1.0, phrase_time_limit=PHRASE_LIMIT)
                except sr.WaitTimeoutError:
                    continue
                # начало фразы = конец записи минус её длина (без паузы в конце и запаса в начале)
                seconds = len(audio.frame_data) / float(audio.sample_rate * audio.sample_width)
                started = time.time() - seconds + self.recognizer.pause_threshold + 0.3
                audio_q.put((audio, started))   # «слушает» мозг покажет, только если фраза обращена к Chloe (см. listener)

    def recognize(self, audio):
        import speech_recognition as sr

        try:
            return self.recognizer.recognize_google(audio, language=LANG)
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            print("[распознавание недоступно: " + str(e) + "]")
            return ""
        finally:
            brain.voice(0, "user")

    # --- голос ---
    def say(self, text):
        text = redact(text)
        print("Chloe:", text)
        journal.add("said", "Голос", text)
        brain.reply(text)
        self.saying = text
        try:
            if self.enabled:
                # голоса по очереди: основной (CHLOE_TTS) → второй → системный; svetlana — только Светлана, без запасных
                engines = {"piper": [self._say_piper, self._say_edge], "edge": [self._say_edge, self._say_piper],
                           "svetlana": [self._say_edge]}
                if not any(engine(text) for engine in engines.get(TTS, engines["piper"])) and TTS != "svetlana":
                    self._say_pyttsx3(text)
            else:
                time.sleep(min(4, 0.6 + len(text) * 0.03))
        finally:
            self.saying = ""
            self.spoke_until = time.time()
        brain.state("idle")

    def stop_audio(self):
        if self.mixer_ready:
            try:
                import pygame

                pygame.mixer.music.stop()
            except Exception:
                pass

    def _play(self, path):
        """Проигрывает файл; «стоп» обрывает на полуслове."""
        import pygame

        if interrupt.is_set():
            return
        if not self.mixer_ready:
            pygame.mixer.init()
            self.mixer_ready = True
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if interrupt.is_set():
                pygame.mixer.music.stop()
                break
            time.sleep(0.05)
        pygame.mixer.music.unload()

    def load_piper(self):
        """Офлайн-голос Piper. Модель грузится ~3 секунды, поэтому один раз и заранее (в фоне при запуске)."""
        with self.piper_lock:
            if self.piper is None and not self.piper_failed:
                model = VOICES_DIR / (PIPER_VOICE + ".onnx")
                if not model.exists():
                    self.piper_failed = True
                    print("[голос Piper не установлен — python run.py --install-voice; пока говорю голосом Microsoft]")
                    return None
                try:
                    from piper import PiperVoice

                    self.piper = PiperVoice.load(str(model))
                    print("[{} голос Piper ({}, офлайн) готов]".format("основной" if TTS == "piper" else "запасной", PIPER_VOICE))
                except Exception as e:
                    self.piper_failed = True
                    print("[Piper: " + str(e)[:80] + "]")
        return self.piper

    def _say_piper(self, text):
        """Офлайн-голос: озвучка за доли секунды, без интернета и без отправки текста куда-либо."""
        piper = self.load_piper()
        if piper is None:
            return False
        fd, path = tempfile.mkstemp(suffix=".wav", dir=DATA)
        os.close(fd)
        try:
            with wave.open(path, "wb") as wav:
                piper.synthesize_wav(text, wav)
            self._play(path)
            return True
        except Exception as e:
            print("[Piper: " + str(e)[:80] + "]")
            return False
        finally:
            os.remove(path)

    def _say_edge(self, text):
        """Голос Светланы (Microsoft, нужен интернет). Длинный ответ — частями по предложениям: следующая часть
        озвучивается, пока звучит текущая, поэтому даже длинный ответ из поиска говорит Светлана, а не запасной голос."""
        if time.time() < self.voice_down_until:
            return False
        parts = pieces(text)
        if not parts:
            return True
        if STREAMING and speech_stream.available() and not interrupt.is_set():
            # с первого кусочка звука, не дожидаясь всей фразы
            try:
                if speech_stream.speak(parts, VOICES[0], interrupt):
                    return True
                self.voice_down_until = time.time() + 60
                return False
            except Exception as e:   # звуковое устройство и т.п. — говорим по-старому, целым файлом
                print("[потоковый голос: " + str(e)[:80] + " — говорю целым файлом]")
        from concurrent.futures import ThreadPoolExecutor

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            jobs = [pool.submit(voice_mp3, p) for p in parts[:2]]
            for i in range(len(parts)):
                data = jobs[i].result()
                if i + 2 < len(parts):
                    jobs.append(pool.submit(voice_mp3, parts[i + 2]))
                if interrupt.is_set():
                    return True
                if data is None:
                    self.voice_down_until = time.time() + 60
                    if i == 0:
                        return False          # Светлана недоступна — весь ответ скажет запасной голос
                    return self._say_piper(" ".join(parts[i:])) or True
                fd, path = tempfile.mkstemp(suffix=".mp3", dir=DATA)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
                    self._play(path)
                finally:
                    os.remove(path)
            return True
        except Exception as e:
            print("[голос Светланы: " + str(e)[:80] + "]")
            return False
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _say_pyttsx3(self, text):
        try:
            import pyttsx3

            if self.tts_engine is None:
                self.tts_engine = pyttsx3.init()
                lang = LANG.split("-")[0].lower()   # ru, uz, en
                for v in self.tts_engine.getProperty("voices"):
                    # точное совпадение языка: подстрока «ru» есть и в «belarusian»
                    tags = {str(x).lower().strip("\x05") for x in v.languages} | {v.id.lower().rsplit("/", 1)[-1], v.name.lower()}
                    if lang in tags or {"ru": "russian", "uz": "uzbek", "en": "english"}.get(lang) in tags:
                        self.tts_engine.setProperty("voice", v.id)
                        break
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except Exception as e:
            print("[озвучка недоступна: " + str(e)[:80] + "]")

    def ask_yes_no(self, question):
        """Подтверждение голосом (или с клавиатуры в текстовом режиме)."""
        self.say(question + " Скажите «да, делай» или «нет».")
        ans = ""
        if self.enabled:
            # ждём до 16 секунд: голосом или ответом в строке ввода окна
            drain(heard_q)
            self.awaiting = True
            deadline = time.time() + 16
            try:
                while not ans and time.time() < deadline and not interrupt.is_set():
                    try:
                        ans = commands.get_nowait().lower()
                    except queue.Empty:
                        try:
                            ans = heard_q.get(timeout=0.5).lower()
                        except queue.Empty:
                            pass
            finally:
                self.awaiting = False
            print("Вы (подтверждение):", ans or "— не услышала ответа")
        else:
            ans = input("(да/нет) > ").lower()
        said = set(words(ans))
        return bool(said & YES_WORDS) and not (said & NO_WORDS)


def pieces(text, size=300, first=140):
    """Текст — частями по предложениям, не длиннее size; первая часть короче (first) — чтобы Светлана начала говорить
    быстрее, а остальное озвучивалось, пока она говорит."""
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?…])\s+|\n+", str(text).strip()):
        s = s.strip()
        while len(s) > size:   # очень длинное предложение — режем по запятой или пробелу
            cut = max(s.rfind(", ", 0, size), s.rfind(" ", 0, size))
            cut = cut + 1 if cut > size // 2 else size
            if cur:
                out.append(cur)
                cur = ""
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if not s:
            continue
        if cur and len(cur) + 1 + len(s) > (size if out else first):
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out


def voice_mp3(text, timeout=60):
    """mp3 голосом Светланы (edge-tts) — для колонок компьютера и для телефона. None — Светлана недоступна.
    Медленный сервер — не повод менять голос: ждём до timeout секунд и пробуем ещё раз.
    Запасной голос — только когда до Microsoft не достучаться (нет интернета)."""
    try:
        import edge_tts
    except ImportError as e:
        print("[edge-tts: " + str(e)[:80] + "]")
        return None

    async def go():
        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, VOICES[0]).stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return bytes(buf)

    problem = None
    for _ in range(3):
        started = time.time()
        try:
            data = asyncio.run(asyncio.wait_for(go(), timeout))
            if data:
                if time.time() - started > 8:
                    print("[сервер голоса медленный: {:.0f} с на {} символов]".format(time.time() - started, len(text)))
                return data
        except Exception as e:
            problem = e
            if time.time() - started < 3:   # отказ сразу — нет связи; подождём секунду и ещё раз
                time.sleep(1)
    print("[голос {} недоступен ({}) — говорю запасным]".format(VOICES[0], type(problem).__name__ if problem else "пусто"))
    return None

voice = Voice(enabled=True)


LONG_WORDS = 8          # после стольких слов речь считается длинной: ждём паузу дольше — человек может задуматься
LONG_PAUSE_EXTRA = 0.8  # секунды к PAUSE для длинной речи; короткие команды по-прежнему отвечают быстро


def finish_speech(text):
    """Ждёт, пока человек договорит: части, сказанные с паузами, склеиваются в одну просьбу.
    Конец — когда тишина длится дольше PAUSE (у длинной речи — чуть дольше) и всё записанное уже распознано."""
    deadline = time.time() + max(PHRASE_LIMIT, CONTINUE_MAX)
    while time.time() < deadline:
        try:
            text += " " + heard_q.get(timeout=0.2)
            continue
        except queue.Empty:
            pass
        pause = PAUSE + (LONG_PAUSE_EXTRA if len(words(text)) >= LONG_WORDS else 0)
        still_talking = time.time() - voice.last_loud < pause
        if not still_talking and audio_q.empty() and not voice.recognizing:
            break
    return text


def recorder():
    """Поток записи: держит микрофон открытым и складывает фразы в очередь."""
    while True:
        try:
            voice.record()
        except Exception as e:
            print("[микрофон: " + str(e)[:80] + "]")
            time.sleep(2)


CONTINUE_MAX = float(os.environ.get("CHLOE_CONTINUE", "60"))   # секунды: самая длинная просьба после «Хлоя» (с паузами)
SHORT_PHRASE = 2.5   # секунды: короткую фразу, сказанную пока Chloe работает, проверяем в Google — вдруг это «стоп»


def route_phrase(audio, started):
    """Решает на компьютере, что делать с фразой, ещё до интернета.
    "cloud" — распознать в Google; "stop" — пользователь сказал «стоп»; "skip" — сказано не Хлое, никуда не уходит."""
    overlapped = bool(voice.saying) or started < voice.spoke_until   # могла звучать сама Chloe
    if not config.WAKE_OFFLINE:
        return "cloud"
    if voice.awaiting and not overlapped:
        return "cloud"                                   # ответ «да/нет» на её вопрос
    working = busy.is_set() or overlapped
    if not working and time.time() < state["listen_until"]:
        voice.reason = "window"
        return "cloud"                                   # окно после её ответа
    if not working and started < voice.open_until:
        voice.reason = "continue"
        return "cloud"                                   # продолжение начатой просьбы
    local = ears.hear(audio)
    if local is None:
        return "cloud"                                   # офлайн-слуха нет — как раньше
    if working:
        own = set(words(voice.saying))
        if is_stop(local) and not (set(words(local)) & set(STOP_WORDS) & own):
            return "stop"
        seconds = len(audio.frame_data) / float(audio.sample_rate * audio.sample_width)
        return "cloud" if seconds <= SHORT_PHRASE else "skip"
    if has_wake(local):
        voice.reason = "wake"
        return "cloud"
    if local:   # шум без слов не печатаем — его слишком много
        print("[не Хлое — не отправлено: {}]".format(local[:60]))
        overheard(local)
    return "skip"


def overheard(text):
    """Речь в комнате, сказанная не Хлое, — в журнал (только на этом компьютере, в Google не уходит).
    Одиночные слова — обычно шум или обрывки, их не храним."""
    if config.OVERHEAR and len(words(text)) >= 2:
        journal.add("overheard", "Слух", text)


def open_continuation(now=None):
    """Фраза ушла на распознавание: следующая часть той же просьбы тоже уйдёт, но не дольше CONTINUE_MAX от её начала —
    иначе непрерывная речь (телевизор, видео) держала бы окно открытым бесконечно."""
    now = now or time.time()
    if voice.reason in ("wake", "window"):
        voice.open_origin = now
    voice.open_until = min(now + PAUSE + LONG_PAUSE_EXTRA + 1.5, voice.open_origin + CONTINUE_MAX)
    voice.reason = ""


def interrupt_now(text):
    print("Вы (перебили):", text)
    interrupt.set()
    voice.stop_audio()


def listener():
    """Поток слуха: распознаёт записанные фразы. Работает всегда, даже пока Chloe думает и говорит, — чтобы её можно было перебить."""
    while True:
        audio, started = audio_q.get()
        voice.recognizing = True
        try:
            way = route_phrase(audio, started)
            if way == "stop":
                interrupt_now("стоп (узнала офлайн)")
                continue
            if way == "skip":
                if not busy.is_set() and time.time() > state["listen_until"]:
                    brain.state("idle")
                continue
            open_continuation()
            if not busy.is_set() or voice.awaiting:
                brain.voice(0.7, "user")
                brain.state("listening")
            text = voice.recognize(audio)
        finally:
            voice.recognizing = False
            brain.voice(0, "user")
        if not text:
            continue
        overlapped = bool(voice.saying) or started < voice.spoke_until
        if voice.awaiting and not overlapped:
            heard_q.put(text)
        elif busy.is_set() or overlapped:
            own = set(words(voice.saying))
            if is_stop(text) and not (set(words(text)) & set(STOP_WORDS) & own):
                interrupt_now(text)
        else:
            heard_q.put(text)


def confirm(question):
    if config.CONFIRM == "off":
        journal.add("confirm", "Подтверждение", question + " — без вопроса (CHLOE_CONFIRM=off)")
        return True
    yes = voice.ask_yes_no(question)
    state["declined"] = state["declined"] or not yes
    journal.add("confirm", "Подтверждение", question + (" — да" if yes else " — нет"), {"question": question, "yes": yes}, ok=yes)
    return yes
