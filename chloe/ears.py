"""Офлайн-слух: слово «Хлоя» узнаётся прямо на компьютере (Vosk), без интернета.

В Google на распознавание уходит только то, что обращено к Chloe: фраза со словом «Хлоя»,
продолжение этой фразы, ответ в течение ACTIVE_WINDOW секунд после её ответа и «да/нет» на её вопрос.
Остальная речь в комнате не покидает компьютер.

Модель — vosk-model-small-ru (45 МБ) в ~/.chloe/ears; ставится командой python run.py --install-ears.
"""
import json
import threading
import time

from .config import EARS_DIR, EARS_MODEL, WAKE_WORDS
from .signals import words

MODEL_URL = "https://alphacephei.com/vosk/models/{}.zip"


class Ears:
    def __init__(self):
        self.model = None
        self.failed = False
        self.lock = threading.Lock()

    def load(self):
        """Модель грузится один раз (~1 с). None — офлайн-слуха нет, всё работает как раньше."""
        with self.lock:
            if self.model is None and not self.failed:
                path = EARS_DIR / EARS_MODEL
                if not path.exists():
                    self.failed = True
                    print("[офлайн-слово «Хлоя» не установлено — python run.py --install-ears; "
                          "пока вся речь распознаётся в Google]")
                    return None
                try:
                    from vosk import Model, SetLogLevel

                    SetLogLevel(-1)
                    self.model = Model(str(path))
                    print("[офлайн-слух готов: в Google уходит только то, что сказано Хлое]")
                except Exception as e:
                    self.failed = True
                    print("[офлайн-слух: " + str(e)[:80] + "]")
        return self.model

    def hear(self, audio):
        """Текст фразы, распознанный на компьютере (грубо — только чтобы найти «Хлоя» и «стоп»). None — офлайн-слуха нет."""
        model = self.load()
        if model is None:
            return None
        from vosk import KaldiRecognizer

        rec = KaldiRecognizer(model, 16000)
        rec.AcceptWaveform(audio.get_raw_data(convert_rate=16000, convert_width=2))
        return json.loads(rec.FinalResult()).get("text", "")


ears = Ears()


NOT_WAKE = {"хлоп", "хлор", "хлев", "клон", "клоп"}   # похожи на «Хлоя», но обычные слова


def near(a, b):
    """Отличаются не больше чем одной буквой (замена, лишняя или пропущенная)."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def is_wake_word(w):
    """«Хлоя» — и то, во что её превращает распознавание: «хлоа», «клоя», «хло»…"""
    w = w.lower()
    if w in WAKE_WORDS:
        return True
    return (3 <= len(w) <= 5 and w[0] in "хк" and w not in NOT_WAKE
            and any(near(w, base) for base in ("хлоя", "хлое", "хлои", "хлою")))


def has_wake(text):
    return any(is_wake_word(w) for w in words(text))


def install(model=EARS_MODEL):
    """Скачивает модель Vosk в ~/.chloe/ears."""
    import io
    import zipfile

    import requests

    target = EARS_DIR / model
    if target.exists():
        print("Уже установлено:", target)
        return
    EARS_DIR.mkdir(parents=True, exist_ok=True)
    url = MODEL_URL.format(model)
    print("Скачиваю", url, "(~45 МБ)…")
    started = time.time()
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(EARS_DIR)
    print("Готово за {:.0f} с: {}".format(time.time() - started, target))
