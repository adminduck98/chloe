"""Слух на компьютере — GigaAM-v3 (Сбер, лицензия MIT): русская речь в текст без интернета и без оплаты, с запятыми,
точками и «ё». Сборка для sherpa-onnx (csukuangfj/sherpa-onnx-nemo-ctc-punct-giga-am-v3-russian-2025-12-16), int8,
225 МБ — в ~/.chloe/ears/gigaam-v3; ставится командой python run.py --install-gigaam.
Скорость на процессоре: фраза 11 с — около 0,9 с (замер 20.11.2026). Модель грузится один раз (~1,3 с) при первой фразе.
"""
import io
import threading
import time
import wave

from . import config

DIR = config.EARS_DIR / "gigaam-v3"
BASE = "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-ctc-punct-giga-am-v3-russian-2025-12-16/resolve/main/"
FILES = ("model.int8.onnx", "tokens.txt", "LICENSE")
THREADS = 2                                    # старый компьютер: не забирать все ядра

_lock = threading.Lock()
_rec = None


def exists():
    return all((DIR / f).exists() for f in FILES[:2])


def available():
    if not exists():
        return False
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return True


def _recognizer():
    global _rec
    if _rec is None:
        import sherpa_onnx

        _rec = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(model=str(DIR / "model.int8.onnx"),
                                                           tokens=str(DIR / "tokens.txt"), num_threads=THREADS)
    return _rec


def samples(wav_bytes):
    """WAV (моно, 16 бит) → частота и отсчёты float32 от −1 до 1."""
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("нужен 16-битный WAV, а не {}-битный".format(8 * width))
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return rate, a


def asr(wav_bytes):
    """Текст фразы ("" — речи нет)."""
    rate, a = samples(wav_bytes)
    if len(a) < rate * 0.25:                   # обрывок короче четверти секунды — не речь
        return ""
    with _lock:                                # один распознаватель на всех: фразы по очереди
        rec = _recognizer()
        s = rec.create_stream()
        s.accept_waveform(rate, a)
        rec.decode_stream(s)
        return s.result.text.strip()


def install():
    """Скачивает модель (~225 МБ) в ~/.chloe/ears/gigaam-v3."""
    import requests

    if exists():
        print("Уже установлено:", DIR)
        return
    DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    for f in FILES:
        print("Скачиваю", f, "…")
        part = DIR / (f + ".part")
        with requests.get(BASE + f, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(part, "wb") as out:
                for chunk in r.iter_content(1 << 20):
                    out.write(chunk)
        part.rename(DIR / f)
    print("Готово за {:.0f} с: {}".format(time.time() - started, DIR))
