"""Интерфейс как герой мультфильма: курсор, который двигается, кликает и тащит; окна, которые тащат, бьют и разбивают.

Жанр «стикмен против интерфейса» — свои герои и свой рабочий стол, не копия чужих серий. Сцену описывает сценарист:
  "windows": [{"id": "w1", "x": 0.55, "y": 0.2, "w": 0.3, "h": 0.32, "color": "blue"}]    — x, y — левый верх (доли кадра);
  "cursor":  [{"t": 0.0, "x": 0.9, "y": 0.1}, {"t": 0.2, "x": 0.6, "y": 0.22, "grab": "w1"},
              {"t": 0.45, "x": 0.3, "y": 0.3, "release": true}, ...]                      — t — доля сцены, grab — окно или герой;
  удар (punch, kick, fight) с "target": id окна — окно разлетается осколками на кадре удара.
Время здесь — секунды сцены (Scene переводит доли в секунды).
"""
import math
import random

GRAVITY = 2.6          # доли высоты кадра в секунду² — осколки и уроненный герой падают «мультяшно» быстро


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


class Cursor:
    """Курсор: точки пути со временем, нажат ли, что держит. Между точками — плавно, с лёгким «доводом» (как рука)."""

    def __init__(self, keys, secs, w, h):
        self.w, self.h = w, h
        self.keys = sorted(({"t": float(k.get("t", 0)) * secs, "x": float(k.get("x", 0.5)) * w, "y": float(k.get("y", 0.5)) * h,
                             "grab": k.get("grab"), "release": bool(k.get("release")), "click": bool(k.get("click"))}
                            for k in keys or []), key=lambda k: k["t"])
        self.grabs = []                                   # (что, t0, t1)
        held, since = None, 0.0
        for k in self.keys:
            if k["grab"]:
                if held:
                    self.grabs.append((held, since, k["t"]))
                held, since = str(k["grab"]), k["t"]
            elif k["release"] and held:
                self.grabs.append((held, since, k["t"]))
                held = None
        if held:
            self.grabs.append((held, since, secs + 1.0))

    def __bool__(self):
        return bool(self.keys)

    def pos(self, t):
        ks = self.keys
        if not ks:
            return None
        if t <= ks[0]["t"]:
            return ks[0]["x"], ks[0]["y"]
        for a, b in zip(ks, ks[1:]):
            if a["t"] <= t <= b["t"]:
                k = _ease((t - a["t"]) / max(b["t"] - a["t"], 1e-3))
                over = math.sin(math.pi * k) * 0.04 * (1 - k)          # чуть проскакивает и возвращается
                return a["x"] + (b["x"] - a["x"]) * (k + over), a["y"] + (b["y"] - a["y"]) * (k + over)
        return ks[-1]["x"], ks[-1]["y"]

    def velocity(self, t, dt=0.04):
        p0, p1 = self.pos(t - dt), self.pos(t)
        return ((p1[0] - p0[0]) / dt, (p1[1] - p0[1]) / dt) if p0 and p1 else (0.0, 0.0)

    def holding(self, t):
        for what, a, b in self.grabs:
            if a <= t < b:
                return what, a
        return None, None

    def presses(self):
        """Моменты нажатия (клик, захват) — для вспышки кольца и звука."""
        return [k["t"] for k in self.keys if k["grab"] or k["click"]]

    def releases(self):
        return [(what, b) for what, _a, b in self.grabs]


class Windows:
    """Окна на рабочем столе: где каждое в момент t (его могли тащить), когда разбито и куда летят осколки."""

    def __init__(self, specs, cursor, w, h, breaks):
        self.w, self.h = w, h
        self.items = []
        for i, s in enumerate(specs or []):
            self.items.append({"id": str(s.get("id") or "w{}".format(i + 1)), "x": float(s.get("x", 0.55)) * w,
                               "y": float(s.get("y", 0.2)) * h, "w": float(s.get("w", 0.3)) * w, "h": float(s.get("h", 0.3)) * h,
                               "color": s.get("color", "blue")})
        self.cursor = cursor
        self.broken = {}                                    # id → (время, точка удара)
        for wid, t, at in breaks:
            if wid in self.ids() and wid not in self.broken:
                self.broken[wid] = (t, at)
        self.shards = {wid: self._shards(wid) for wid in self.broken}

    def ids(self):
        return [it["id"] for it in self.items]

    def get(self, wid):
        return next((it for it in self.items if it["id"] == wid), None)

    def offset(self, wid, t):
        """Сдвиг окна от исходного места: пока курсор его держит — едет за курсором, потом остаётся там, где отпустили."""
        dx = dy = 0.0
        if not self.cursor:
            return dx, dy
        for what, a, b in self.cursor.grabs:
            if what != wid or t < a:
                continue
            p0 = self.cursor.pos(a)
            p1 = self.cursor.pos(min(t, b))
            dx += p1[0] - p0[0]
            dy += p1[1] - p0[1]
        return dx, dy

    def rect(self, wid, t):
        it = self.get(wid)
        dx, dy = self.offset(wid, t)
        return it["x"] + dx, it["y"] + dy, it["w"], it["h"]

    def _shards(self, wid):
        """Окно → 18 осколков-треугольников; каждый летит от точки удара, крутится и падает."""
        tb, at = self.broken[wid]
        x, y, ww, hh = self.rect(wid, tb)
        rng = random.Random(hash(wid) & 0xFFFF)
        cols, rows = 4, 3
        pts = [[(x + ww * (c + (rng.uniform(-0.2, 0.2) if 0 < c < cols else 0)) / cols,
                 y + hh * (r + (rng.uniform(-0.2, 0.2) if 0 < r < rows else 0)) / rows) for c in range(cols + 1)] for r in range(rows + 1)]
        out = []
        hx, hy = at if at else (x + ww / 2, y + hh / 2)
        for r in range(rows):
            for c in range(cols):
                a, b, cc, d = pts[r][c], pts[r][c + 1], pts[r + 1][c + 1], pts[r + 1][c]
                for tri in ((a, b, cc), (a, cc, d)):
                    cx, cy = sum(p[0] for p in tri) / 3, sum(p[1] for p in tri) / 3
                    ang = math.atan2(cy - hy, cx - hx)
                    sp = rng.uniform(0.35, 0.8) * self.h
                    out.append({"tri": [(p[0] - cx, p[1] - cy) for p in tri], "c": (cx, cy),
                                "v": (math.cos(ang) * sp, math.sin(ang) * sp - rng.uniform(0.2, 0.5) * self.h),
                                "spin": rng.uniform(-9, 9)})
        return out

    def draw(self, c, t, colors):
        held = self.cursor.holding(t)[0] if self.cursor else None
        for it in self.items:
            wid = it["id"]
            if wid in self.broken and t >= self.broken[wid][0]:
                continue
            x, y, ww, hh = self.rect(wid, t)
            lift = self.h * (0.018 if held == wid else 0.008)            # тень: поднятое окно отбрасывает её дальше
            c.set_source_rgba(0, 0, 0, 0.45)
            _rr(c, x + lift, y + lift * 1.4, ww, hh, self.h * 0.012)
            c.fill()
            draw_window(c, (x, y, ww, hh), colors.get(it["color"], colors["blue"]), self.h)

    def draw_shards(self, c, t, colors, ground):
        for wid, shards in self.shards.items():
            tb, _ = self.broken[wid]
            k = t - tb
            if k < 0 or k > 1.6:
                continue
            col = colors.get(self.get(wid)["color"], colors["blue"])
            alpha = 1.0 if k < 0.9 else max(0.0, 1 - (k - 0.9) / 0.7)
            for s in shards:
                cx = s["c"][0] + s["v"][0] * k
                cy = min(ground, s["c"][1] + s["v"][1] * k + 0.5 * GRAVITY * self.h * k * k)
                a = s["spin"] * k
                c.save()
                c.translate(cx, cy)
                c.rotate(a)
                c.move_to(*s["tri"][0])
                for p in s["tri"][1:]:
                    c.line_to(*p)
                c.close_path()
                c.set_source_rgba(*col, 0.28 * alpha)
                c.fill_preserve()
                c.set_source_rgba(*col, 0.9 * alpha)
                c.set_line_width(max(1.0, self.h * 0.002))
                c.stroke()
                c.restore()


def draw_window(c, rect, col, h):
    """Окно приложения: полупрозрачное тело, заголовок, три кнопки; светится цветом окна."""
    x, y, ww, hh = rect
    r = h * 0.012
    c.set_source_rgba(0.07, 0.08, 0.15, 0.92)                            # настоящее окно непрозрачное — не путается с фоном
    _rr(c, x, y, ww, hh, r)
    c.fill()
    c.set_source_rgba(*col, 0.16)
    _rr(c, x, y, ww, hh, r)
    c.fill()
    c.set_source_rgba(*col, 1.0)
    c.set_line_width(max(1.5, h * 0.003))
    _rr(c, x, y, ww, hh, r)
    c.stroke()
    bar = hh * 0.13
    c.set_source_rgba(*col, 0.9)
    _rr(c, x, y, ww, bar, r)
    c.fill()
    for i, cc in enumerate(((0.95, 0.35, 0.35), (0.98, 0.78, 0.25), (0.35, 0.85, 0.45))):
        c.set_source_rgb(*cc)
        c.arc(x + ww - bar * (0.6 + i * 0.75), y + bar / 2, bar * 0.22, 0, 2 * math.pi)
        c.fill()
    c.set_source_rgba(*col, 0.35)                                       # «строки» содержимого
    for i in range(3):
        c.rectangle(x + ww * 0.08, y + bar + hh * (0.15 + i * 0.18), ww * (0.7 - i * 0.15), hh * 0.05)
        c.fill()


def draw_cursor(c, pos, h, pressed_for=None, holding=False):
    """Стрелка курсора с чёрной обводкой; при нажатии — расходящееся кольцо, при захвате стрелка чуть меньше."""
    if not pos:
        return
    x, y = pos
    s = h * (0.05 if not holding else 0.044)
    if pressed_for is not None and pressed_for < 0.35:
        k = pressed_for / 0.35
        c.set_source_rgba(1, 1, 1, 0.7 * (1 - k))
        c.set_line_width(max(1.5, h * 0.003))
        c.arc(x, y, s * (0.3 + 1.1 * k), 0, 2 * math.pi)
        c.stroke()
    shape = [(0, 0), (0, 1.0), (0.26, 0.76), (0.45, 1.15), (0.6, 1.08), (0.42, 0.7), (0.75, 0.7)]
    c.move_to(x, y)
    for px, py in shape[1:]:
        c.line_to(x + px * s, y + py * s)
    c.close_path()
    c.set_source_rgb(1, 1, 1)
    c.fill_preserve()
    c.set_source_rgb(0, 0, 0)
    c.set_line_width(max(1.2, h * 0.0022))
    c.stroke()


def _rr(c, x, y, w, h, r):
    c.new_sub_path()
    c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    c.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    c.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    c.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    c.close_path()


def fall_time(height_px, h):
    """Сколько секунд падает с высоты (пиксели) при мультяшной гравитации."""
    return math.sqrt(2 * max(0.0, height_px) / (GRAVITY * h)) if height_px > 0 else 0.0
