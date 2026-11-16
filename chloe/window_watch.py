"""Видно ли окно Chloe — чтобы анимация мозга не тратила процессор впустую (просьба пользователя, 14.11.2026).

Раз в секунду: окно свёрнуто, на другом рабочем столе или целиком закрыто другими окнами — «hidden» (анимация на
паузе); видно, но работаете в другом окне — «background» (в покое реже кадры); активно — «front».
Узнаём у оконного менеджера X11 (python-xlib); на других системах — всегда «front», как было.
CHLOE_ANIM=full — анимация всегда полная, пока окно видно (пауза в свёрнутом окне остаётся: её никто не видит).
"""
import os
import threading
import time

# уровень анимации: low (слабый компьютер), medium (по умолчанию), high (без экономии в покое; full — старое имя)
_level = os.environ.get("CHLOE_ANIM", "medium").strip().lower()
LEVEL = {"full": "high", "auto": "medium", "min": "low", "max": "high"}.get(_level, _level)
if LEVEL not in ("low", "medium", "high"):
    LEVEL = "medium"
FULL = LEVEL
GRID = 6        # окно закрыто, если все точки сетки 6×6 под другими окнами


def covered(rect, others, grid=GRID):
    """Целиком ли прямоугольник rect=(x, y, w, h) закрыт прямоугольниками others."""
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return True
    for i in range(grid):
        for j in range(grid):
            px, py = x + (i + 0.5) * w / grid, y + (j + 0.5) * h / grid
            if not any(ox <= px < ox + ow and oy <= py < oy + oh for ox, oy, ow, oh in others):
                return False
    return True


class Watcher:
    """Состояние окна этого процесса по данным оконного менеджера X11."""

    def __init__(self, pid=None):
        from Xlib import X, display

        self.X = X
        self.d = display.Display()
        self.root = self.d.screen().root
        self.pid = pid or os.getpid()
        self.atom = lambda name: self.d.intern_atom(name)
        self.mine = None

    def _prop(self, win, name, kind=None):
        try:
            p = win.get_full_property(self.atom(name), kind or self.X.AnyPropertyType)
            return list(p.value) if p else []
        except Exception:                           # noqa: BLE001 — окно закрылось между вызовами
            return []

    def _rect(self, win):
        g = win.get_geometry()
        t = win.translate_coords(self.root, 0, 0)
        return (-t.x, -t.y, g.width, g.height)

    def _hidden(self, win):
        return self.atom("_NET_WM_STATE_HIDDEN") in self._prop(win, "_NET_WM_STATE")

    def _desktop(self, win):
        v = self._prop(win, "_NET_WM_DESKTOP")
        return v[0] if v else None

    def find(self):
        for wid in self._prop(self.root, "_NET_CLIENT_LIST"):
            w = self.d.create_resource_object("window", wid)
            if self.pid in self._prop(w, "_NET_WM_PID"):
                return w
        return None

    def state(self):
        if self.mine is None:
            self.mine = self.find()
            if self.mine is None:
                return "front"                      # окна ещё нет — не мешаем
        me = self.mine
        try:
            if self._hidden(me):
                return "hidden"
            now_desk = (self._prop(self.root, "_NET_CURRENT_DESKTOP") or [None])[0]
            desk = self._desktop(me)
            if desk not in (None, 0xFFFFFFFF) and now_desk is not None and desk != now_desk:
                return "hidden"
            stack = self._prop(self.root, "_NET_CLIENT_LIST_STACKING")    # снизу вверх
            above = stack[stack.index(me.id) + 1:] if me.id in stack else []
            others = []
            for wid in above:
                w = self.d.create_resource_object("window", wid)
                if self._hidden(w) or self._desktop(w) not in (None, 0xFFFFFFFF, now_desk):
                    continue
                if self.atom("_NET_WM_WINDOW_TYPE_NORMAL") not in (self._prop(w, "_NET_WM_WINDOW_TYPE") or
                                                                   [self.atom("_NET_WM_WINDOW_TYPE_NORMAL")]):
                    continue                        # панели, подсказки, уведомления окно не закрывают
                try:
                    others.append(self._rect(w))
                except Exception:                   # noqa: BLE001
                    pass
            if others and covered(self._rect(me), others):
                return "hidden"
            active = (self._prop(self.root, "_NET_ACTIVE_WINDOW") or [0])[0]
            return "front" if active == me.id else "background"
        except Exception:                           # noqa: BLE001 — окно пересоздано: найдём заново
            self.mine = None
            return "front"


def start(send, every=1.0, stop=None):
    """Поток: при смене состояния вызывает send(state, full). Без X11 или python-xlib — ничего не делает."""
    if not os.environ.get("DISPLAY"):
        return None
    try:
        watcher = Watcher()
    except Exception as e:                          # noqa: BLE001
        print("[окно: не узнать, видно ли оно ({}) — анимация как раньше]".format(type(e).__name__))
        return None

    def loop():
        last, sent = None, 0.0
        while not (stop and stop.is_set()):
            st = watcher.state()
            # раз в 15 с — повтор: окно могло перезагрузиться (после «забудь») и забыть состояние
            if (st != last or time.time() - sent > 15) and send(st, FULL):
                last, sent = st, time.time()
            time.sleep(every)
    t = threading.Thread(target=loop, daemon=True, name="window-watch")
    t.start()
    return t
