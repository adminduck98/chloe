"""Отпечаток голоса владельца: Chloe узнаёт его голос и отвечает без слова «Хлоя» (опрос владельца, 16.11.2026:
«не хочу каждый раз говорить Хлоя»). Чужие голоса — телевизор, гости, музыка — по-прежнему только по имени.

Как собирается: каждая фраза, где владелец сказал «Хлоя», добавляется в отпечаток (до MAX_SAMPLES), и есть быстрый
путь — «Хлоя, запомни мой голос»: следующие ENROLL_SECONDS секунд Chloe только слушает и запоминает.
Работает с MIN_SAMPLES фраз. Всё на этом компьютере: модель WeSpeaker ResNet34 (sherpa-onnx), отпечаток —
~/.chloe/voiceprint/owner.npy; ни голос, ни отпечаток никуда не уходят.
CHLOE_VOICE_MATCH — порог сходства (0..1, по умолчанию 0.62); CHLOE_WAKE=name — снова только по имени.
"""
import os
import threading

import numpy as np

from .config import DATA

FOLDER = DATA / "voiceprint"
MODEL = FOLDER / "wespeaker_en_voxceleb_resnet34.onnx"
PROFILE = FOLDER / "owner.npy"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
             "wespeaker_en_voxceleb_resnet34.onnx")
THRESHOLD = float(os.environ.get("CHLOE_VOICE_MATCH", "0.62"))
MODE = os.environ.get("CHLOE_WAKE", "voice").strip().lower()      # voice — узнавать голос; name — только «Хлоя»
MIN_SAMPLES = 4
MAX_SAMPLES = 40
MIN_SECONDS = 0.8          # короче — отпечаток ненадёжен («да», «ага»)
ENROLL_SECONDS = 25

_lock = threading.Lock()
_extractor = None
_samples = None


def available():
    if not MODEL.exists():
        return False
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return True


def _ex():
    global _extractor
    if _extractor is None:
        import sherpa_onnx

        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL), num_threads=2)
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    return _extractor


def _pcm(audio):
    """sr.AudioData (или numpy float32 16 кГц) → float32 16 кГц моно."""
    if isinstance(audio, np.ndarray):
        return audio.astype(np.float32)
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def embed(audio):
    """Отпечаток фразы (вектор длины 1) или None, если фраза слишком короткая."""
    pcm = _pcm(audio)
    if len(pcm) < MIN_SECONDS * 16000:
        return None
    with _lock:
        ex = _ex()
        s = ex.create_stream()
        s.accept_waveform(16000, pcm)
        s.input_finished()
        v = np.array(ex.compute(s), dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n else None


def samples():
    global _samples
    if _samples is None:
        try:
            _samples = np.load(PROFILE)
        except (OSError, ValueError):
            _samples = np.zeros((0, 256), np.float32)
    return _samples


def ready():
    return MODE != "name" and available() and len(samples()) >= MIN_SAMPLES


def score(audio):
    """Сходство с голосом владельца (0..1) или None — не с чем сравнить или фраза короткая."""
    s = samples()
    if not len(s):
        return None
    v = embed(audio)
    if v is None:
        return None
    centroid = s.mean(axis=0)
    centroid /= np.linalg.norm(centroid) or 1
    return float(v @ centroid)


def is_owner(audio):
    """(владелец ли, сходство). Не готово или фраза короткая — (False, None)."""
    if not ready():
        return False, None
    sc = score(audio)
    return (sc is not None and sc >= THRESHOLD), sc


def learn(audio):
    """Добавить фразу владельца в отпечаток. Чужая (сильно непохожая при готовом отпечатке) — не добавляется."""
    global _samples
    v = embed(audio)
    if v is None:
        return False
    s = samples()
    if len(s) >= MIN_SAMPLES:
        centroid = s.mean(axis=0)
        centroid /= np.linalg.norm(centroid) or 1
        if float(v @ centroid) < THRESHOLD - 0.15:
            return False                       # «Хлоя» сказал кто-то другой — его голос не смешиваем
    s = np.vstack([s, v[None, :]])[-MAX_SAMPLES:]
    FOLDER.mkdir(parents=True, exist_ok=True)
    np.save(PROFILE, s)
    _samples = s
    return True


def reset():
    global _samples
    try:
        PROFILE.unlink()
    except OSError:
        pass
    _samples = np.zeros((0, 256), np.float32)


def status_text():
    if MODE == "name":
        return "Узнавание голоса выключено (CHLOE_WAKE=name): отвечаю только на «Хлоя»."
    if not available():
        return "Узнавание голоса не установлено: нет модели или sherpa-onnx."
    n = len(samples())
    if n < MIN_SAMPLES:
        return ("Голос владельца ещё не запомнила: {} из {} фраз. Скажите «Хлоя, запомни мой голос» и говорите 20 секунд "
                "или просто обращайтесь ко мне по имени — запомню по ходу.".format(n, MIN_SAMPLES))
    return "Голос владельца знаю ({} фраз): на него отвечаю без «Хлоя», чужие голоса — только по имени.".format(n)
