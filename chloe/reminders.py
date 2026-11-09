"""Напоминания и таймеры: «напомни через 10 минут выключить чайник», «поставь таймер на 5 минут», «напомни в 18:30».

Хранятся в ~/.chloe/chloe.db (таблица reminders) — переживают перезапуск. В срок Chloe говорит вслух,
показывает уведомление и пишет в журнал. Если она в этот момент занята — скажет, как только освободится.
"""
import datetime
import shutil
import sqlite3
import subprocess
import threading
import time

from .config import JOURNAL_FILE
from .journal import journal
from .signals import busy, said_alone, state


class Reminders:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY, due REAL NOT NULL, text TEXT NOT NULL, created REAL NOT NULL, done REAL)""")
        self.db.commit()

    def add(self, due, text):
        with self.lock:
            cur = self.db.execute("INSERT INTO reminders (due, text, created) VALUES (?, ?, ?)", (due, text, time.time()))
            self.db.commit()
            return cur.lastrowid

    def pending(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM reminders WHERE done IS NULL ORDER BY due")]

    def cancel(self, rid):
        with self.lock:
            n = self.db.execute("UPDATE reminders SET done = ? WHERE id = ? AND done IS NULL", (time.time(), rid)).rowcount
            self.db.commit()
            return n > 0

    def due_now(self, now=None):
        now = now or time.time()
        return [r for r in self.pending() if r["due"] <= now]

    def ring(self, say, now=None):
        """Озвучивает всё, чему пришёл срок. Возвращает, сколько напоминаний сказано."""
        rung = 0
        for r in self.due_now(now):
            late = (now or time.time()) - r["due"]
            text = "Напоминаю: " + r["text"]
            if late > 120:   # компьютер спал или Chloe была выключена
                text += " (это было на {})".format(when_text(r["due"]))
            self.cancel(r["id"])
            notify(r["text"])
            journal.add("remind", "Напоминания", r["text"], {"id": r["id"], "due": r["due"], "late_seconds": round(late)})
            said_alone.append("в {} «{}»".format(time.strftime("%H:%M"), text))
            say(text)
            rung += 1
        return rung


def when_text(ts):
    d = datetime.datetime.fromtimestamp(ts)
    today = datetime.date.today()
    day = {today: "", today + datetime.timedelta(days=1): "завтра "}.get(d.date(), d.strftime("%d.%m "))
    return day + d.strftime("%H:%M")


def notify(text):
    if shutil.which("notify-send"):
        try:
            subprocess.Popen(["notify-send", "-a", "Chloe", "-u", "critical", "Хлоя напоминает", text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def due_from(minutes=None, at=None, now=None):
    """Когда сработать: через N минут или в «18:30» / «2026-11-06 09:00». «18:30», которое уже прошло, — завтра."""
    now = now or time.time()
    if minutes is not None:
        return now + float(minutes) * 60
    at = str(at).strip()
    base = datetime.datetime.fromtimestamp(now)
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%H:%M", "%H.%M"):
        try:
            t = datetime.datetime.strptime(at, fmt)
        except ValueError:
            continue
        if fmt in ("%H:%M", "%H.%M"):
            t = base.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if t.timestamp() <= now:
                t += datetime.timedelta(days=1)
        return t.timestamp()
    raise ValueError("Не понимаю время «{}» — нужно, например, 18:30 или 2026-11-06 09:00.".format(at))


def watcher(say):
    """Поток: раз в 5 секунд проверяет срок. Пока Chloe думает или говорит — ждёт, чтобы не перебивать себя."""
    from .voice import voice

    while True:
        time.sleep(5)
        try:
            if busy.is_set() or voice.saying or voice.awaiting:
                continue
            if reminders.ring(say):
                state["listen_until"] = time.time() + 30   # можно ответить без слова «Хлоя»
        except Exception as e:
            print("[напоминания: " + str(e)[:80] + "]")


reminders = Reminders(JOURNAL_FILE)
