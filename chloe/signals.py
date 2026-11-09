"""Общие сигналы между потоками: очереди фраз, «занята», «стоп», команды из окна."""
import collections
import queue
import re
import threading

from .config import STOP_WORDS


audio_q = queue.Queue()          # записанные фразы, ждущие распознавания
heard_q = queue.Queue()          # распознанные фразы
commands = queue.Queue()         # команды, набранные в окне
busy = threading.Event()         # Chloe думает или выполняет просьбу
interrupt = threading.Event()    # пользователь сказал «стоп»
STOPPED = "Остановилась по просьбе пользователя."
state = {"declined": False,      # в текущем действии пользователь сказал «нет»
         "listen_until": 0.0}    # до этого времени Chloe слушает без слова «Хлоя» (после своего ответа)
# что Chloe сказала сама, без просьбы (напоминания): модель узнает об этом с ближайшей просьбой,
# иначе на «ты же не напомнила» она решит, что напоминания не было
said_alone = collections.deque(maxlen=10)


def words(text):
    return re.findall(r"\w+", text.lower())


def is_stop(text):
    """Короткая фраза со стоп-словом: «стоп», «Хлоя, хватит», «замолчи»."""
    w = words(text)
    return 0 < len(w) <= 3 and any(x in STOP_WORDS for x in w)


def drain(q):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return
