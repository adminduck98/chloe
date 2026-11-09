"""Постоянное зрение: Chloe всё время видит экран, а не только когда сама делает скриншот.

Как работает:
- Фоновый поток раз в несколько секунд смотрит на экран: какое окно активно и что на нём.
- Кадры хранятся только в памяти (последний кадр и короткая история окон) — на диск ничего не пишется.
- К каждой просьбе мозг получает: какое окно сейчас открыто, какие окна были последние минуты
  и свежий кадр экрана (если модель умеет смотреть на картинки). Поэтому «что это за ошибка?»,
  «переведи вот это», «закрой это» работают без лишнего скриншота.
- Приватные окна (пароли, банки, режим инкогнито) Chloe не смотрит: кадр не берётся и не хранится.
- Выключается голосом («не смотри на экран») или в окне Chloe; настройка — vision в ~/.chloe/settings.json.
"""
import collections
import io
import re
import subprocess
import threading
import time

from .config import OS_NAME
from .settings import settings

INTERVAL = 2.0          # раз во сколько секунд смотреть
FRESH = 15.0            # кадр старше — к просьбе не прикладывается (экран мог смениться, а глаза отстали)
FRAME_WIDTH = 1280      # как у инструмента screenshot: координаты для mouse_click совпадают
CHANGE = 6.0            # средняя разница яркости (0–255), после которой экран «сменился»
HISTORY_MINUTES = 10

PRIVATE = re.compile(
    r"(парол|password|passwort|1password|bitwarden|keepass|lastpass|dashlane|"
    r"банк|bank|сбербанк|sberbank|тинькофф|tinkoff|kaspi|payme|click\.uz|uzcard|humo|"
    r"инкогнито|incognito|private browsing|приватн|inprivate|"
    r"вход в аккаунт|sign in|log ?in|войти)",
    re.IGNORECASE)


# просьба, скорее всего, про то, что на экране: к ней прикладываем кадр. К остальным («поставь будильник») —
# только название окна: так дешевле и быстрее. Настройка vision_frames: "auto" (по умолчанию) или "always".
SCREEN_HINT = re.compile(
    r"(?<![а-яё])(это|эт[ау]|этот|этим|тут|здесь|вот|экран\w*|видишь|видно|ошибк\w*|окн[оаеу]\w*|переведи|прочитай|"
    r"прочти|написано|кнопк\w*|сайт\w*|страниц\w*|вкладк\w*|картинк\w*|фото|таблиц\w*|код\w*|открыт\w*|"
    r"нажми|кликни|выдели|скопируй)(?![а-яё])", re.IGNORECASE)


def wants_frame(text):
    """Нужен ли к просьбе кадр экрана."""
    if settings.get("vision_frames", "auto") == "always":
        return True
    return bool(SCREEN_HINT.search(text or ""))


def private_title(title, extra=()):
    """Окно, на которое смотреть нельзя: пароли, банки, инкогнито, вход в аккаунты — и что добавил пользователь."""
    t = title or ""
    return bool(PRIVATE.search(t)) or any(w and w.lower() in t.lower() for w in extra)


def _run(cmd, timeout=1.5):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def active_window():
    """Заголовок активного окна (Windows, macOS, Linux). Пустая строка, если узнать нельзя."""
    if OS_NAME == "Windows":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            return buf.value
        except Exception:
            return ""
    if OS_NAME == "Darwin":
        app = _run(["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'])
        win = _run(["osascript", "-e", 'tell application "System Events" to tell (first application process whose frontmost is true) '
                                       'to get name of front window']) if app else ""
        return " — ".join(x for x in (win, app) if x)
    title = _run(["xdotool", "getactivewindow", "getwindowname"])
    if title:
        return title
    wid = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    m = re.search(r"(0x[0-9a-f]+)", wid)
    if m:
        name = _run(["xprop", "-id", m.group(1), "_NET_WM_NAME"])
        m2 = re.search(r'= "(.*)"$', name)
        if m2:
            return m2.group(1)
    return ""


def grab():
    """Снимок экрана (PIL.Image) и ширина экрана в логических точках — для пересчёта координат кликов."""
    import pyautogui

    img = pyautogui.screenshot()
    return img, pyautogui.size()[0]


class Vision:
    def __init__(self, capture=grab, title_of=active_window, clock=time.time):
        self.capture, self.title_of, self.clock = capture, title_of, clock
        self.lock = threading.Lock()
        self.frame = None          # JPEG последнего кадра
        self.frame_at = 0.0
        self.size = (0, 0)
        self.title = ""
        self.private = False
        self.thumb = None          # маленький серый кадр — сравнивать, сменился ли экран
        self.history = collections.deque(maxlen=60)   # (время, заголовок окна)
        self.thread = None
        self.on_window = None      # куда сообщать о смене окна (мозг в окне Chloe)
        self.errors = 0

    # ---------- включено ли ----------
    @property
    def enabled(self):
        return bool(settings.get("vision", True))

    def set_enabled(self, on):
        settings.set("vision", bool(on))
        if not on:
            with self.lock:
                self.frame, self.thumb = None, None
        return self.enabled

    def private_words(self):
        return [str(w) for w in settings.get("vision_private", []) if str(w).strip()]

    # ---------- глаза ----------
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True, name="chloe-vision")
        self.thread.start()

    def _loop(self):
        while True:
            try:
                if self.enabled:
                    self.tick()
                    self.errors = 0
            except Exception as e:   # нет дисплея, нет прав на запись экрана — глаза не роняют Chloe
                self.errors += 1
                if self.errors in (1, 30):
                    print("[зрение: не вижу экран — {}]".format(e))
            time.sleep(INTERVAL if self.errors < 5 else 15)

    def tick(self):
        """Один взгляд на экран."""
        now = self.clock()
        title = self.title_of() or ""
        changed_window = title != self.title
        if changed_window:
            with self.lock:
                self.title = title
                self.history.append((now, title))
            if self.on_window:
                try:
                    self.on_window(title, private_title(title, self.private_words()))
                except Exception:
                    pass
        if private_title(title, self.private_words()):
            with self.lock:   # приватное окно: кадр не берём, старый забываем
                self.private, self.frame, self.thumb = True, None, None
            return
        img, logical_w = self.capture()
        thumb = img.convert("L").resize((64, 36))
        moved = self._difference(thumb)
        if not changed_window and not moved and self.frame is not None:
            with self.lock:
                self.private, self.frame_at = False, now   # экран тот же — кадр по-прежнему свежий
            return
        w = min(FRAME_WIDTH, img.width)
        h = int(img.height * w / img.width)
        small = img.resize((w, h)).convert("RGB")
        buf = io.BytesIO()
        small.save(buf, format="JPEG", quality=70)
        with self.lock:
            self.private = False
            self.frame, self.frame_at, self.size, self.thumb = buf.getvalue(), now, (w, h), thumb
            self.ratio = logical_w / w if w else 1.0

    def _difference(self, thumb):
        if self.thumb is None:
            return True
        a, b = thumb.tobytes(), self.thumb.tobytes()   # серый кадр 64×36: байт на точку
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a) > CHANGE

    # ---------- что видит — для мозга ----------
    def fresh_frame(self):
        """JPEG свежего кадра или None (выключено, приватное окно, кадр устарел)."""
        if not self.enabled:
            return None
        with self.lock:
            if self.private or self.frame is None or self.clock() - self.frame_at > FRESH:
                return None
            ratio = getattr(self, "ratio", 1.0)
            frame = self.frame
        from .tools import screen

        screen.state["ratio"] = ratio   # клик по координатам этого кадра попадёт куда надо
        return frame

    def context(self):
        """Строка для просьбы: что сейчас на экране и какие окна были недавно."""
        if not self.enabled:
            return ""
        now = self.clock()
        with self.lock:
            title, private = self.title, self.private
            recent = [(t, w) for t, w in self.history if now - t <= HISTORY_MINUTES * 60 and w]
        if private or private_title(title, self.private_words()):
            return "[Экран: открыто приватное окно (пароли, банк или инкогнито) — ты его не видишь и не смотришь.]"
        parts = []
        if title:
            parts.append("сейчас активно окно «{}»".format(title[:120]))
        earlier = []
        for t, w in reversed(recent[:-1]):
            if w != title and not private_title(w, self.private_words()) and w not in [e[1] for e in earlier]:
                earlier.append((t, w))
            if len(earlier) >= 4:
                break
        if earlier:
            parts.append("до этого: " + "; ".join("{} «{}»".format(time.strftime("%H:%M", time.localtime(t)), w[:70])
                                                   for t, w in earlier))
        if not parts:
            return ""
        seen = ""   # о кадре скажет сама просьба: он приложен, только когда она про экран (wants_frame)
        return "[Экран: {}.{} «Это», «тут», «вот это» — скорее всего про то, что на экране.]".format(". ".join(parts), seen)

    def recent(self, minutes=HISTORY_MINUTES):
        now = self.clock()
        with self.lock:
            rows = [(t, w) for t, w in self.history if now - t <= minutes * 60 and w]
        rows = [(t, "приватное окно" if private_title(w, self.private_words()) else w) for t, w in rows]
        return rows


vision = Vision()


def tool_vision(a):
    """Голосом: включить/выключить постоянное зрение, узнать, что было на экране."""
    action = str(a.get("action", "status"))
    if action == "off":
        vision.set_enabled(False)
        return "Постоянное зрение выключено: на экран смотрю, только когда делаю скриншот по задаче."
    if action == "on":
        vision.set_enabled(True)
        vision.start()
        return "Постоянное зрение включено: вижу экран всё время, приватные окна пропускаю."
    if action == "hide":
        word = str(a.get("word", "")).strip()
        if not word:
            return "Не сказано, какое окно не смотреть."
        words = vision.private_words()
        if word.lower() not in [w.lower() for w in words]:
            settings.set("vision_private", words + [word])
        return "Окна со словом «{}» больше не смотрю.".format(word)
    if action == "history":
        rows = vision.recent(int(a.get("minutes") or HISTORY_MINUTES))
        if not rows:
            return "За это время окна не менялись или зрение было выключено."
        return "\n".join("{} — {}".format(time.strftime("%H:%M", time.localtime(t)), w) for t, w in rows)
    state = "включено" if vision.enabled else "выключено"
    return "Постоянное зрение {}. Сейчас окно: {}.".format(state, vision.title or "неизвестно")
