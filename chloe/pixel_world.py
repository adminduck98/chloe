"""Пиксельный мир «внутри игры» и пиксельный герой — всё рисует код, без нейросетей (роадмап 2.0).

Как устроено:
  • кадр рисуется маленьким (216×384 для Shorts или 384×216) и увеличивается ровно в 5 раз «по пикселям» —
    1080×1920 / 1920×1080, пиксели остаются чёткими квадратами;
  • современный пиксель-арт: свет сверху-слева (каждая фигура сама получает блик и тень по краю), тёмная обводка,
    мягкое свечение у светящихся вещей (порталы, монеты), параллакс в несколько слоёв, частицы;
  • герой — на скелете мультипликатора (chloe/animator.py): все его движения (ходьба, бег, прыжок, записи живых
    движений, эмоции) работают и здесь; рисуется заново — пикселями, с угловатыми плечами и круглой головой;
  • мир — уровень-платформер: земля из плиток, ямы, платформы, блоки с «?», монеты, шипы, портал, HUD.

ВНИМАНИЕ: облик героя временный — по описанию (круглая голова, угловатые плечи). Когда владелец пришлёт рисунок
своего стикмена, HERO перерисовывается точно по нему.
"""
import math
import os
import pathlib
import subprocess

import numpy as np

SCALE = 5
FPS = 30
TILE = 16


def rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


# ---------------------------------------------------------------- палитра (своя)
P = {k: rgb(v) for k, v in {
    "ink": "1a0f1f", "ink2": "2c1a35",
    "sky0": "160b2e", "sky1": "231245", "sky2": "34185c", "sky3": "4c2170", "sky4": "6e2c7d", "sky5": "9a3d84",
    "star": "fff6d6", "moon": "ffe7b8", "moon2": "e8c48e",
    "mtn0": "2a1f55", "mtn1": "3b2b6b", "mtn2": "54408a",
    "hill0": "173f52", "hill1": "1f5a63", "hill2": "2d7a72",
    "cloud": "c8b6e8", "cloud2": "8f7fc0",
    "grass0": "1f7a4d", "grass1": "35b062", "grass2": "7be07a", "grass3": "c8ff9e",
    "dirt0": "3d2121", "dirt1": "5c3227", "dirt2": "7e4632", "dirt3": "a0633f",
    "brick0": "3a3556", "brick1": "5a5480", "brick2": "8a83b3",
    "gold0": "9c4f17", "gold1": "e0891f", "gold2": "ffc93d", "gold3": "fff1a8",
    "used0": "4a2c22", "used1": "6e4433",
    "steel0": "4f5570", "steel1": "8d96b0", "steel2": "d8deec",
    "port0": "153d8a", "port1": "2794d6", "port2": "5fe6ff", "port3": "e6ffff",
    "skin0": "b9a58a", "skin1": "e6d8bf", "skin2": "fff7e8",
    "acc0": "a8343f", "acc1": "ff6f73", "acc2": "ffb0a8",
    "heart": "ff4f6d", "white": "ffffff",
}.items()}


# ---------------------------------------------------------------- холст и примитивы
class Layer:
    """Слой: цвет + прозрачность (0/1) + «излучение» для свечения."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.c = np.zeros((h, w, 3), np.float32)
        self.a = np.zeros((h, w), np.float32)
        self.e = np.zeros((h, w, 3), np.float32)

    def put(self, mask, col, emit=0.0):
        self.c[mask] = col
        self.a[mask] = 1.0
        if emit:
            self.e[mask] = col * emit


def _grid(w, h):
    ys, xs = np.mgrid[0:h, 0:w]
    return xs.astype(np.float32) + 0.5, ys.astype(np.float32) + 0.5


def disc_mask(w, h, cx, cy, r, xs=None, ys=None):
    if xs is None:
        xs, ys = _grid(w, h)
    return (xs - cx) ** 2 + (ys - cy) ** 2 <= r * r


def seg_mask(xs, ys, a, b, r):
    """Пиксели не дальше r от отрезка ab — толстая линия с круглыми концами."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy or 1e-6
    t = np.clip(((xs - ax) * dx + (ys - ay) * dy) / L, 0, 1)
    px, py = ax + t * dx, ay + t * dy
    return (xs - px) ** 2 + (ys - py) ** 2 <= r * r


def poly_mask(xs, ys, pts):
    """Многоугольник (чётно-нечётное правило)."""
    inside = np.zeros(xs.shape, bool)
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cond = ((y1 > ys) != (y2 > ys)) & (xs < (x2 - x1) * (ys - y1) / ((y2 - y1) or 1e-6) + x1)
        inside ^= cond
    return inside


def shift(m, dx, dy):
    out = np.zeros_like(m)
    h, w = m.shape
    xs0, xs1 = max(0, dx), min(w, w + dx)
    ys0, ys1 = max(0, dy), min(h, h + dy)
    out[ys0:ys1, xs0:xs1] = m[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def bevel(mask):
    """Свет сверху-слева: край, у которого сверху-слева пусто, — блик; снизу-справа — тень."""
    lit = mask & ~shift(mask, 1, 1)
    dark = mask & ~shift(mask, -1, -1)
    return lit & ~dark, dark & ~lit


def outline(mask):
    grown = mask | shift(mask, 1, 0) | shift(mask, -1, 0) | shift(mask, 0, 1) | shift(mask, 0, -1)
    return grown & ~mask


def blur(img, r):
    """Быстрое размытие (два прохода коробкой) — для свечения."""
    out = img
    for axis in (0, 1):
        for _ in range(2):
            pad = [(0, 0)] * out.ndim
            pad[axis] = (r, r)
            p = np.pad(out, pad, mode="edge")
            cs = np.cumsum(p, axis=axis, dtype=np.float32)
            cs = np.concatenate([np.zeros_like(np.take(cs, [0], axis=axis)), cs], axis=axis)
            hi = np.take(cs, range(2 * r + 1, 2 * r + 1 + out.shape[axis]), axis=axis)
            lo = np.take(cs, range(0, out.shape[axis]), axis=axis)
            out = (hi - lo) / (2 * r + 1)
    return out


def hsh(*v):
    """Детерминированный «шум» для узоров (одинаковый в каждом кадре)."""
    x = 0
    for k in v:
        x = (x * 73856093) ^ (int(k) * 19349663) ^ 0x5bd1e995
        x &= 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 1274126177) & 0xFFFFFFFF
    return (x ^ (x >> 16)) / 0xFFFFFFFF


# ---------------------------------------------------------------- пиксельный текст (цифры HUD)
DIGITS = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111", "4": "101101111001001",
    "5": "111100111001111", "6": "111100111101111", "7": "111001010010010", "8": "111101111101111", "9": "111101111001111",
    "+": "000010111010000", "x": "000101010101000",
}


def draw_digits(layer, text, x, y, col, s=1, shadow=True):
    for i, ch in enumerate(text):
        g = DIGITS.get(ch)
        if not g:
            continue
        for k, bit in enumerate(g):
            if bit == "1":
                px, py = x + i * 4 * s + (k % 3) * s, y + (k // 3) * s
                if shadow:
                    layer.c[py + s:py + 2 * s, px + s:px + 2 * s] = P["ink"]
                    layer.a[py + s:py + 2 * s, px + s:px + 2 * s] = 1
                layer.c[py:py + s, px:px + s] = col
                layer.a[py:py + s, px:px + s] = 1


def draw_text(layer, text, cx, y, size=11, col=None, emit=0.0):
    """Надпись пиксельным шрифтом без сглаживания (кириллица — системный TrueType в режиме «1 бит»)."""
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"):
        if os.path.exists(f):
            font = ImageFont.truetype(f, size)
            break
    font = font or ImageFont.load_default()
    im = Image.new("1", (layer.w, size * 2), 0)
    d = ImageDraw.Draw(im)
    d.fontmode = "1"
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, 0), text, fill=1, font=font)
    m = np.zeros((layer.h, layer.w), bool)
    arr = np.array(im, bool)
    h = min(arr.shape[0], layer.h - y)
    m[y:y + h] = arr[:h]
    layer.put(outline(m) | shift(outline(m), 1, 1), P["ink"])
    layer.put(m, col if col is not None else P["white"], emit)
    hi, _ = bevel(m)
    layer.put(hi & m, P["gold3"] if col is None else np.minimum(1, (col if col is not None else P["white"]) * 1.15))


# ---------------------------------------------------------------- ГЕРОЙ
HERO = {
    "height": 64,                  # рост в пикселях низкого разрешения
    "upper": 2.3, "fore": 1.8, "thigh": 2.4, "shin": 1.9,           # полутолщины рук и ног
    "shoulder": 5.5, "waist": 2.6,  # полуширина плеч (угловатые) и талии
    "body": ("skin0", "skin1", "skin2"), "accent": ("acc0", "acc1", "acc2"),
    "scarf": True,                 # временно: шарф-акцент цвета Chloe — уберём, если на рисунке его нет
}


def _shade_part(layer, mask, ramp, back=False):
    """Часть тела: основной цвет, блик и тень по краю; дальняя рука/нога — на тон темнее."""
    lo, mid, hi = (P[k] for k in ramp)
    if back:
        lo, mid, hi = lo * 0.72, lo * 0.95, mid * 0.9
    layer.put(mask, mid)
    lit, dark = bevel(mask)
    layer.put(dark, lo)
    layer.put(lit, hi)


def draw_hero(layer, pose, x, ground, facing=1, emotion="neutral", t=0.0, scale=1.0, alpha=1.0, front=False):
    """Пиксельный герой: скелет — из мультипликатора, рисунок — свой. Возвращает точки суставов (для эффектов)."""
    from . import animator as A

    size = HERO["height"] * scale
    pts, r = A.skeleton(pose, x, ground, size, facing, front=front)
    w, h = layer.w, layer.h
    xs_all, ys_all = _grid(w, h)
    # работаем в окне вокруг героя — быстрее
    x0, x1 = int(max(0, x - size)), int(min(w, x + size))
    y0, y1 = int(max(0, ground - size * 1.6)), int(min(h, ground + 4))
    if x1 <= x0 or y1 <= y0:
        return pts
    xs, ys = xs_all[y0:y1, x0:x1], ys_all[y0:y1, x0:x1]
    sub = Layer(x1 - x0, y1 - y0)
    k = scale
    o = lambda p: (p[0] - x0, p[1] - y0)                                        # noqa: E731
    P_ = {n: o(p) for n, p in pts.items()}

    def limb(side):
        m = seg_mask(xs - x0, ys - y0, P_["shoulder"], P_["el" + side], HERO["upper"] * k) | \
            seg_mask(xs - x0, ys - y0, P_["el" + side], P_["hand" + side], HERO["fore"] * k)
        hand = disc_mask(0, 0, *P_["hand" + side], HERO["fore"] * k + 0.9, xs - x0, ys - y0)
        leg = seg_mask(xs - x0, ys - y0, P_["hip"], P_["kn" + side], HERO["thigh"] * k) | \
            seg_mask(xs - x0, ys - y0, P_["kn" + side], P_["foot" + side], HERO["shin"] * k)
        fx, fy = P_["foot" + side]
        boot = (np.abs(xs - x0 - fx - facing * 1.5 * k) <= 2.6 * k) & (ys - y0 >= fy - 2.2 * k) & (ys - y0 <= fy + 0.8 * k)
        return m | hand, leg, boot

    xs_l, ys_l = xs - x0, ys - y0
    # туловище: угловатые плечи (трапеция от плеч к талии)
    hx, hy = P_["hip"]
    sx, sy = P_["neck"]
    ax, ay = sx - hx, sy - hy
    L = math.hypot(ax, ay) or 1
    nx, ny = -ay / L, ax / L
    S, Wt = HERO["shoulder"] * k, HERO["waist"] * k
    top = (sx - ax / L * 1.2 * k, sy - ay / L * 1.2 * k)
    torso = poly_mask(xs_l, ys_l, [(top[0] + nx * S, top[1] + ny * S), (top[0] - nx * S, top[1] - ny * S),
                                    (sx - ax / L * -3 * k - nx * S, sy - ay / L * -3 * k - ny * S),
                                    (hx - nx * Wt, hy - ny * Wt), (hx + nx * Wt, hy + ny * Wt),
                                    (sx - ax / L * -3 * k + nx * S, sy - ay / L * -3 * k + ny * S)])
    hc = P_["head"]
    head = disc_mask(0, 0, hc[0], hc[1], r + 0.6, xs_l, ys_l)
    arm1, leg1, boot1 = limb("1")
    arm2, leg2, boot2 = limb("2")
    body = arm1 | arm2 | leg1 | leg2 | torso | head | boot1 | boot2
    # шарф: два хвоста, развеваются назад
    scarf = np.zeros_like(body)
    if HERO["scarf"]:
        nk = P_["neck"]
        wave = math.sin(t * 9.0)
        tail1 = (nk[0] - facing * 7 * k, nk[1] + (1.5 + wave * 1.5) * k)
        tail2 = (nk[0] - facing * 11 * k, nk[1] + (3.5 - wave * 1.2) * k)
        scarf = seg_mask(xs_l, ys_l, (nk[0] - facing * 1 * k, nk[1] + 0.5 * k), tail1, 1.6 * k) | \
            seg_mask(xs_l, ys_l, tail1, tail2, 1.2 * k) | seg_mask(xs_l, ys_l, (nk[0] - 2.5 * k, nk[1] + 0.8 * k), (nk[0] + 2.5 * k, nk[1] + 0.8 * k), 1.5 * k)
        body = body | scarf
    sub.put(outline(body), P["ink"])
    # сзади вперёд: дальняя рука и нога, туловище, голова, ближняя рука и нога
    for m in (leg2, boot2, arm2):
        _shade_part(sub, m, HERO["body"], back=True)
    sub.put(boot2, P["ink2"])
    _shade_part(sub, torso, HERO["body"])
    _shade_part(sub, leg1, HERO["body"])
    sub.put(boot1, P["ink2"])
    lit, _ = bevel(boot1)
    sub.put(lit & boot1, P["brick1"])
    if HERO["scarf"]:
        _shade_part(sub, scarf, HERO["accent"])
    _shade_part(sub, head, HERO["body"])
    sel = outline(arm1) & (torso | head | leg1)                     # ближняя рука отделена тонкой линией
    sub.put(sel, P["skin0"] * 0.7)
    _shade_part(sub, arm1, HERO["body"])
    # лицо
    ex = hc[0] + facing * r * 0.38
    ey = hc[1] - r * 0.1
    blink = (t % 3.1) < 0.12
    eye_h = 1 if blink or emotion == "happy" else 2
    for dx in (0, facing * r * 0.62) if not front else (-r * 0.4, r * 0.4):
        ex2 = (hc[0] + dx) if front else ex + dx
        ix, iy = int(round(ex2)), int(round(ey))
        if 0 <= iy < sub.h and 0 <= ix < sub.w:
            sub.c[iy - eye_h + 1:iy + 1, ix:ix + 1] = P["ink"]
            sub.a[iy - eye_h + 1:iy + 1, ix:ix + 1] = 1
    mx = int(round(hc[0] + (0 if front else facing * r * 0.5)))
    my = int(round(hc[1] + r * 0.45))
    mouth = {"happy": [(-1, 0), (0, 1), (1, 0)], "sad": [(-1, 1), (0, 0), (1, 1)], "surprised": [(0, 0), (0, 1)],
             "angry": [(-1, 0), (0, 0), (1, 0)], "think": [(0, 0), (1, 0)]}.get(emotion, [(0, 0), (1, 0)] if not front else [(-1, 0), (0, 0), (1, 0)])
    for dx, dy in mouth:
        px, py = mx + dx, my + dy
        if 0 <= py < sub.h and 0 <= px < sub.w:
            sub.c[py, px] = P["ink"]
            sub.a[py, px] = 1
    if emotion in ("happy", "surprised", "neutral"):               # румянец
        cx_, cy_ = int(round(hc[0] + (facing * r * 0.15 if not front else -r * 0.55))), int(round(hc[1] + r * 0.25))
        if 0 <= cy_ < sub.h and 0 <= cx_ < sub.w:
            sub.c[cy_, cx_] = P["acc2"]
    # блик на голове
    bx, by = int(round(hc[0] - r * 0.45)), int(round(hc[1] - r * 0.55))
    if 0 <= by < sub.h and 0 <= bx + 1 < sub.w:
        sub.c[by, bx:bx + 2] = P["white"]
    # контровой свет справа (от портала/неба) — тонкая полоска по краю
    rim = body & ~shift(body, -1, 0) & ~outline(body)
    sub.c[rim] = np.minimum(1, sub.c[rim] * 0.6 + P["port2"] * 0.45)
    _blend(layer, sub, x0, y0, alpha)
    return pts


def _blend(dst, src, x0, y0, alpha=1.0):
    h, w = src.a.shape
    a = (src.a * alpha)[..., None]
    region = dst.c[y0:y0 + h, x0:x0 + w]
    dst.c[y0:y0 + h, x0:x0 + w] = region * (1 - a) + src.c * a
    dst.a[y0:y0 + h, x0:x0 + w] = np.maximum(dst.a[y0:y0 + h, x0:x0 + w], src.a * alpha)
    dst.e[y0:y0 + h, x0:x0 + w] += src.e * a


# ---------------------------------------------------------------- МИР: уровень
class Level:
    """Уровень-платформер. Сетка плиток: '.' пусто, '#' земля, '=' платформа, '?' блок, '^' шипы, 'o' монета, '@' портал."""

    def __init__(self, rows, ground_row):
        self.rows = [list(r) for r in rows]
        self.h = len(rows)
        self.w = max(len(r) for r in rows)
        for r in self.rows:
            r.extend("." * (self.w - len(r)))
        self.ground_row = ground_row
        self.bumped = {}            # (col,row) → время удара
        self.taken = {}             # монеты: (col,row) → время

    def at(self, c, r):
        if 0 <= r < self.h and 0 <= c < self.w:
            return self.rows[r][c]
        return "."

    def solid(self, c, r):
        return self.at(c, r) in "#=?U"



GROUND_ROW = 17
DEPTH = 40


def build_level(features, length):
    """Уровень из списка препятствий: (колонка, вид, параметр). Виды: spikes n, gap n, block (блок «?»),
    pillar n (столбик высотой n), coins n (ряд монет на уровне груди), portal."""
    rows = [["."] * length for _ in range(DEPTH)]
    for r in range(GROUND_ROW, DEPTH):
        for c in range(length):
            rows[r][c] = "#"
    for col, kind, n in features:
        if kind == "spikes":
            for c in range(col, col + n):
                rows[GROUND_ROW - 1][c] = "^"
        elif kind == "gap":
            for c in range(col, col + n):
                for r in range(GROUND_ROW, DEPTH):
                    rows[r][c] = "."
        elif kind == "block":
            rows[GROUND_ROW - 6][col] = "?"            # низ блока выше головы: под ним можно пробежать
        elif kind == "pillar":
            for r in range(GROUND_ROW - n, GROUND_ROW):
                rows[r][col] = "="
        elif kind == "coins":
            for c in range(col, col + n):
                rows[GROUND_ROW - 2][c] = "o"
        elif kind == "portal":
            rows[GROUND_ROW - 1][col] = "@"
    return Level(["".join(r) for r in rows], GROUND_ROW)


DEMO = [(9, "coins", 3), (16, "block", 0), (24, "spikes", 2), (31, "coins", 2), (36, "gap", 3), (45, "pillar", 2),
        (50, "coins", 3), (56, "spikes", 3), (66, "portal", 0)]
DEMO_LEN = 74


def make_demo_level():
    return build_level(DEMO, DEMO_LEN)


# ---------------------------------------------------------------- фоновые слои (рисуются один раз)
def sky_layer(w, h):
    L = Layer(w, h)
    ramp = ["sky0", "sky1", "sky2", "sky3", "sky4", "sky5"]
    xs = np.arange(w)
    for y in range(h):
        f = (y / h) ** 1.3 * len(ramp)
        k = min(len(ramp) - 1, int(f))
        L.c[y] = P[ramp[k]]
        if k + 1 < len(ramp) and f - k > 0.86:                              # шахматка на стыке полос — как в играх
            L.c[y, (xs + y) % 2 == 0] = P[ramp[k + 1]]
    L.a[:] = 1
    return L


def stars(L, t, w, h, cam, seed=1):
    for i in range(70):
        x = (hsh(seed, i, 1) * w * 3 - cam * 0.05) % w
        y = hsh(seed, i, 2) * h * 0.55
        tw = 0.5 + 0.5 * math.sin(t * (1.5 + hsh(seed, i, 3) * 3) + i)
        if tw < 0.35:
            continue
        xi, yi = int(x), int(y)
        L.c[yi, xi] = P["star"] * (0.6 + 0.4 * tw)
        if hsh(seed, i, 4) > 0.86 and 1 <= xi < w - 1 and 1 <= yi < h - 1 and tw > 0.8:       # крупные — крестиком
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                L.c[yi + dy, xi + dx] = P["star"] * 0.55


def moon(L, w, h, cam):
    xs, ys = _grid(w, h)
    cx, cy, r = w * 0.72 - cam * 0.02, h * 0.16, 17
    m = disc_mask(w, h, cx, cy, r, xs, ys)
    L.put(m, P["moon"], emit=0.35)
    for (dx, dy, rr) in ((-5, -4, 3.5), (6, 3, 2.5), (-1, 8, 2), (8, -7, 1.6)):
        L.put(m & disc_mask(w, h, cx + dx, cy + dy, rr, xs, ys), P["moon2"], emit=0.2)
    sh = m & ~disc_mask(w, h, cx - 5, cy - 4, r, xs, ys)
    L.put(sh, P["moon2"] * 0.85, emit=0.1)


def ridge(width, h, base, amp, seed, step=4, smooth=6):
    """Силуэт гор/холмов: высота по колонкам, ступеньками по 2 пикселя."""
    n = width // step + 2
    raw = np.array([hsh(seed, i) for i in range(n + smooth)])
    sm = np.convolve(raw, np.ones(smooth) / smooth, mode="valid")[:n]
    peaks = np.array([hsh(seed, i // 9, 7) for i in range(n)])
    tops = base - (sm * 0.6 + peaks * 0.4) * amp
    return np.repeat((tops // 2) * 2, step)[:width]


def far_layer(width, h, seed):
    L = Layer(width, h)
    tops = ridge(width, h, h * 0.62, h * 0.2, seed, step=2, smooth=14)
    ys = np.arange(h)[:, None]
    m = ys >= tops[None, :]
    L.put(m, P["mtn1"])
    lit = m & ~shift(m, 2, 2)
    L.put(lit, P["mtn2"])
    tops2 = ridge(width, h, h * 0.72, h * 0.1, seed + 5, step=2, smooth=10)
    m2 = ys >= tops2[None, :]
    L.put(m2, P["mtn0"])
    return L


def mid_layer(width, h, seed):
    L = Layer(width, h)
    tops = ridge(width, h, h * 0.8, h * 0.1, seed, step=2, smooth=10)
    ys, xs = np.mgrid[0:h, 0:width]
    m = ys >= tops[None, :]
    L.put(m, P["hill1"])
    L.put(m & ~shift(m, 1, 2), P["hill2"])
    # деревья-столбики с круглыми кронами
    for i in range(width // 46):
        tx = int(hsh(seed, i, 11) * 40 + i * 46)
        ty = int(tops[min(width - 1, tx)])
        rr = 7 + int(hsh(seed, i, 12) * 6)
        trunk = (np.abs(xs - tx) <= 1) & (ys >= ty - rr - 4) & (ys <= ty)
        crown = disc_mask(0, 0, tx, ty - rr - 6, rr, xs + 0.5, ys + 0.5)
        L.put(trunk, P["hill0"])
        L.put(crown, P["hill1"])
        hi, lo = bevel(crown)
        L.put(hi, P["hill2"])
        L.put(lo, P["hill0"])
    L.put(m & (ys >= tops[None, :] + 26), P["hill0"])
    return L


def cloud_layer(width, h, seed):
    L = Layer(width, h)
    xs, ys = _grid(width, h)
    for i in range(width // 120 + 1):
        cx = hsh(seed, i, 21) * 80 + i * 120
        cy = h * (0.18 + hsh(seed, i, 22) * 0.2)
        m = np.zeros((h, width), bool)
        for j in range(5):
            m |= disc_mask(width, h, cx + (j - 2) * 7, cy + (abs(j - 2) * 2), 7 - abs(j - 2), xs, ys)
        m &= ys < cy + 5
        L.put(m, P["cloud2"])
        L.put(m & ~shift(m, 0, 2), P["cloud"])
    return L


def compose(dst, src, offset_x):
    """Слой шириной больше кадра — сдвинутый на offset_x (параллакс), по кругу."""
    w = dst.w
    xs = (np.arange(w) + int(offset_x)) % src.w
    a = src.a[:, xs][..., None]
    dst.c[:] = dst.c * (1 - a) + src.c[:, xs] * a
    dst.e += src.e[:, xs] * a


# ---------------------------------------------------------------- плитки уровня
def draw_tiles(L, level, cam_x, cam_y, t):
    w, h = L.w, L.h
    c0, c1 = int(cam_x // TILE) - 1, int((cam_x + w) // TILE) + 2
    r0, r1 = int(cam_y // TILE) - 1, int((cam_y + h) // TILE) + 2
    xs, ys = _grid(TILE, TILE)
    for r in range(max(0, r0), min(level.h, r1)):
        for c in range(max(0, c0), min(level.w, c1)):
            ch = level.at(c, r)
            if ch == ".":
                continue
            x, y = int(c * TILE - cam_x), int(r * TILE - cam_y)
            if ch == "?" and (c, r) in level.bumped:
                dt = t - level.bumped[(c, r)]
                if 0 <= dt < 0.25:
                    y -= int(round(math.sin(dt / 0.25 * math.pi) * 4))
            tile = _tile(level, c, r, ch, t, xs, ys)
            if tile is None:
                continue
            _blit(L, tile, x, y)


_tile_cache = {}


def _tile(level, c, r, ch, t, xs, ys):
    if ch == "#":
        top = not level.solid(c, r - 1)
        key = ("#", top, c % 4, r % 3)
        if key in _tile_cache:
            return _tile_cache[key]
        T = Layer(TILE, TILE)
        T.put(np.ones((TILE, TILE), bool), P["dirt1"])
        for i in range(3):                                                      # камешки
            px, py = int(hsh(c, r, i) * 14) + 1, int(hsh(r, c, i + 9) * 14) + 1
            peb = disc_mask(TILE, TILE, px, py, 1.6, xs, ys)
            T.put(peb, P["dirt2"])
            T.put(peb & ~shift(peb, 1, 1), P["dirt3"])
            T.put(peb & ~shift(peb, -1, -1) & ~(peb & ~shift(peb, 1, 1)), P["dirt0"])
        if top:
            edge = np.array([int(3 + hsh(c * 16 + k, 77) * 3) for k in range(TILE)])
            m = np.arange(TILE)[:, None] < edge[None, :]
            T.put(m, P["grass1"])
            T.put(m & (np.arange(TILE)[:, None] < 2), P["grass2"])
            T.put(m & (np.arange(TILE)[:, None] == 0), P["grass3"])
            T.put(outline(m) & (np.arange(TILE)[:, None] > 1), P["grass0"])
            for k in range(TILE):                                               # травинки над краем
                if hsh(c, k, 5) > 0.82:
                    T.c[0, k] = P["grass3"]
        _tile_cache[key] = T
        return T
    if ch == "=":
        key = ("=", c % 2)
        if key not in _tile_cache:
            T = Layer(TILE, TILE)
            T.put(np.ones((TILE, TILE), bool), P["brick1"])
            for yy in (0, 8):
                T.put(np.zeros((TILE, TILE), bool) | ((np.arange(TILE)[:, None] == yy + 7) & np.ones((1, TILE), bool)), P["brick0"])
            off = 4 if c % 2 else 12
            for yy, xx in ((0, off), (8, (off + 8) % 16)):
                T.c[yy:yy + 7, xx] = P["brick0"]
            T.c[0, :] = P["brick2"]
            T.c[8, :] = P["brick2"] * 0.9
            _tile_cache[key] = T
        return _tile_cache[key]
    if ch in "?U":
        used = ch == "U" or (c, r) in level.bumped
        key = ("?", used)
        if key not in _tile_cache:
            T = Layer(TILE, TILE)
            full = np.ones((TILE, TILE), bool)
            inner = np.zeros((TILE, TILE), bool)
            inner[1:-1, 1:-1] = True
            T.put(full, P["ink"])
            T.put(inner, P["used1"] if used else P["gold1"])
            hi, lo = bevel(inner)
            T.put(hi, P["used1"] * 1.2 if used else P["gold2"])
            T.put(lo, P["used0"] if used else P["gold0"])
            for (yy, xx) in ((2, 2), (2, 13), (13, 2), (13, 13)):
                T.c[yy, xx] = P["used0"] if used else P["gold3"]
            if not used:
                q = ["01110", "10001", "00011", "00110", "00100", "00000", "00100"]
                for yy, row in enumerate(q):
                    for xx, b in enumerate(row):
                        if b == "1":
                            T.c[4 + yy, 5 + xx] = P["gold3"]
                            T.c[5 + yy, 6 + xx] = P["gold0"]
                T.e[inner] = P["gold2"] * 0.12
            _tile_cache[key] = T
        return _tile_cache[key]
    if ch == "^":
        key = ("^",)
        if key not in _tile_cache:
            T = Layer(TILE, TILE)
            m = np.zeros((TILE, TILE), bool)
            for k in range(4):
                cx = k * 4 + 2
                m |= poly_mask(xs, ys, [(cx - 2, 16), (cx + 2, 16), (cx, 6)])
            T.put(outline(m) & (ys < 16), P["ink"])
            T.put(m, P["steel1"])
            hi, lo = bevel(m)
            T.put(hi, P["steel2"])
            T.put(lo, P["steel0"])
            _tile_cache[key] = T
        return _tile_cache[key]
    if ch == "o":
        if (c, r) in level.taken:
            return None
        frame = int(t * 10 + c) % 6
        key = ("o", frame)
        if key not in _tile_cache:
            T = Layer(TILE, TILE)
            wd = [5, 4, 2.2, 1, 2.2, 4][frame]
            m = ((xs - 8) / wd) ** 2 + ((ys - 8) / 6) ** 2 <= 1
            T.put(outline(m), P["ink"])
            T.put(m, P["gold2"], emit=0.5)
            hi, lo = bevel(m)
            T.put(hi, P["gold3"], emit=0.6)
            T.put(lo, P["gold1"], emit=0.3)
            if wd > 3:
                T.put((np.abs(xs - 8) < 0.6) & (np.abs(ys - 8) < 3.6), P["gold1"])
            _tile_cache[key] = T
        return _tile_cache[key]
    return None


def _blit(L, T, x, y):
    h, w = T.a.shape
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    dx1, dy1 = min(L.w, x + w), min(L.h, y + h)
    if dx1 <= dx0 or dy1 <= dy0:
        return
    a = T.a[sy0:sy0 + dy1 - dy0, sx0:sx0 + dx1 - dx0][..., None]
    L.c[dy0:dy1, dx0:dx1] = L.c[dy0:dy1, dx0:dx1] * (1 - a) + T.c[sy0:sy0 + dy1 - dy0, sx0:sx0 + dx1 - dx0] * a
    L.e[dy0:dy1, dx0:dx1] += T.e[sy0:sy0 + dy1 - dy0, sx0:sx0 + dx1 - dx0] * a


def draw_portal(L, x, y, t, open_k=1.0):
    """Портал: овал из вращающихся колец, свечение, искры. x, y — центр низа на экране."""
    w, h = L.w, L.h
    xs, ys = _grid(w, h)
    cx, cy = x, y - 22
    rx, ry = 11 * open_k, 20 * open_k
    if rx < 1:
        return
    d = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2
    ang = np.arctan2(ys - cy, xs - cx)
    ring = (d <= 1) & (d > 0.72)
    L.put(outline(d <= 1), P["ink"])
    L.put(d <= 1, P["port0"], emit=0.6)
    swirl = (d <= 0.72) & (np.sin(ang * 3 + d * 9 - t * 7) > 0.35)
    L.put(swirl, P["port1"], emit=0.9)
    L.put((d <= 0.25) & (np.sin(ang * 2 - t * 9) > 0), P["port2"], emit=1.0)
    L.put(ring, P["port2"], emit=1.0)
    L.put(ring & (np.sin(ang * 8 + t * 6) > 0.6), P["port3"], emit=1.2)
    for i in range(10):                                                         # искры вокруг
        a = t * 2.2 + i * 0.63
        rr = 1.15 + 0.15 * math.sin(t * 3 + i)
        px, py = int(cx + math.cos(a) * rx * rr), int(cy + math.sin(a) * ry * rr)
        if 0 <= px < w and 0 <= py < h:
            L.c[py, px] = P["port3"]
            L.e[py, px] = P["port3"] * 1.5


# ---------------------------------------------------------------- частицы
class Particles:
    def __init__(self):
        self.items = []

    def add(self, kind, x, y, vx=0.0, vy=0.0, life=0.6, col=None, text=None):
        self.items.append({"k": kind, "x": x, "y": y, "vx": vx, "vy": vy, "t": 0.0, "life": life, "col": col, "text": text})

    def dust(self, x, y, n=5, dirx=0):
        for i in range(n):
            self.add("dust", x + (hsh(x, i) - 0.5) * 6, y - 1, (hsh(i, x, 2) - 0.5) * 30 - dirx * 20, -hsh(i, y) * 18, 0.45)

    def sparkle(self, x, y, n=8):
        for i in range(n):
            a = i / n * math.tau
            self.add("spark", x, y, math.cos(a) * 55, math.sin(a) * 55, 0.4, P["gold3"])

    def step(self, dt):
        for p in self.items:
            p["t"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            if p["k"] == "dust":
                p["vy"] += 20 * dt
                p["vx"] *= 0.9
            elif p["k"] == "spark":
                p["vx"] *= 0.86
                p["vy"] *= 0.86
            elif p["k"] == "score":
                p["vy"] *= 0.9
        self.items = [p for p in self.items if p["t"] < p["life"]]

    def draw(self, L, cam_x, cam_y):
        for p in self.items:
            x, y = int(p["x"] - cam_x), int(p["y"] - cam_y)
            k = 1 - p["t"] / p["life"]
            if p["k"] == "score":
                draw_digits(L, p["text"], x - 6, y, P["gold3"] if k > 0.3 else P["gold1"])
                continue
            if not (0 <= x < L.w - 1 and 0 <= y < L.h - 1):
                continue
            if p["k"] == "dust":
                s = 2 if k > 0.5 else 1
                L.c[y:y + s, x:x + s] = L.c[y:y + s, x:x + s] * 0.3 + P["cloud"] * 0.7
            else:
                L.c[y, x] = p["col"]
                L.e[y, x] = p["col"] * 1.4
                if k > 0.5:
                    L.c[y, x + 1] = p["col"] * 0.8


# ---------------------------------------------------------------- HUD
def draw_hud(L, coins, score, lives):
    w = L.w
    xs, ys = _grid(w, L.h)
    cm = ((xs - 12) / 3.5) ** 2 + ((ys - 13) / 5) ** 2 <= 1                      # монета
    L.put(outline(cm), P["ink"])
    L.put(cm, P["gold2"], emit=0.4)
    L.put(cm & ~shift(cm, 1, 1), P["gold3"])
    draw_digits(L, "x" + str(coins).rjust(2, "0"), 19, 10, P["white"])
    draw_digits(L, str(score).rjust(6, "0"), w // 2 - 12, 10, P["white"])
    for i in range(3):                                                          # сердечки
        x0 = w - 12 - i * 11
        hm = disc_mask(w, L.h, x0 - 2, 11, 2.6, xs, ys) | disc_mask(w, L.h, x0 + 2, 11, 2.6, xs, ys) | \
            poly_mask(xs, ys, [(x0 - 4.8, 12), (x0 + 4.8, 12), (x0, 17.5)])
        L.put(outline(hm), P["ink"])
        L.put(hm, P["heart"] if i < lives else P["ink2"])
        if i < lives:
            L.put(hm & ~shift(hm, 1, 1), P["acc2"])


# ---------------------------------------------------------------- финальная сборка кадра
def finish(L, vignette=True):
    """Свечение, лёгкая виньетка, квантование цвета (чтобы оставался пиксель-арт) → uint8 кадр."""
    glow = blur(L.e, 4) * 0.9 + blur(L.e, 10) * 0.5
    img = L.c + glow
    if vignette:
        h, w = L.h, L.w
        ys, xs = np.mgrid[0:h, 0:w]
        v = 1 - 0.28 * (((xs - w / 2) / (w * 0.75)) ** 2 + ((ys - h / 2) / (h * 0.75)) ** 2)
        img = img * v[..., None]
    img = np.clip(img, 0, 1)
    img = np.round(img * 31) / 31                                               # 5 бит на канал — пиксельная палитра
    return (img * 255).astype(np.uint8)


def upscale(frame, s=SCALE):
    return frame.repeat(s, 0).repeat(s, 1)


# ---------------------------------------------------------------- демо-серия: герой проходит уровень
class Demo:
    """Сценарий: герой выходит, бежит, перепрыгивает шипы и яму, бьёт блок, собирает монеты, уходит в портал."""

    def __init__(self, w=216, h=384, features=None, length=None):
        self.w, self.h = w, h
        self.features = features or DEMO
        self.level = build_level(self.features, length or DEMO_LEN)
        self.sky = sky_layer(w, h)
        world_w = self.level.w * TILE
        self.far = far_layer(max(w * 3, int(world_w * 0.25) + w), h, 3)
        self.clouds = cloud_layer(max(w * 3, int(world_w * 0.35) + w), h, 4)
        self.mid = mid_layer(max(w * 3, int(world_w * 0.55) + w), h, 5)
        self.parts = Particles()
        self.coins, self.score, self.lives = 0, 0, 3
        self.ground = GROUND_ROW * TILE
        self.portal_x = next(c for c, k, _ in self.features if k == "portal") * TILE + TILE / 2
        self.speed = 84.0
        self.start_x = 2.5 * TILE
        self.jumps = self._plan_jumps()
        self.prev_air = False
        self.last_step = 0
        self._arc_coins()

    def _plan_jumps(self):
        """Прыжки из списка препятствий: (x начала, длительность, высота). Длина прыжка — с запасом за препятствие."""
        out = []
        for col, kind, n in self.features:
            x0 = col * TILE
            if kind in ("spikes", "gap", "pillar"):
                width = (n if kind != "pillar" else 1) * TILE
                run_up, land = 18, 22
                length = run_up + width + land
                height = {"spikes": 34, "gap": 40, "pillar": n * TILE + 16}[kind]
                out.append((x0 - run_up, length / self.speed, height))
            elif kind == "block":
                # голова упирается в низ блока (а не пролетает сквозь): высота = от макушки до низа блока
                hit = self.ground - HERO["height"] * 1.02 - (GROUND_ROW - 5) * TILE
                out.append((x0 + 8 - 0.5 * 56, 56 / self.speed, max(8, hit)))         # вершина прыжка — под блоком
        return sorted(out)

    def _arc_coins(self):
        """Монеты по дуге над прыжками через ямы — их собирают в воздухе."""
        for (jx, dur, hgt) in self.jumps:
            length = dur * self.speed
            for k in (0.3, 0.5, 0.7):
                x = jx + length * k
                y = self.ground - HERO["height"] * 0.55 - 4 * hgt * k * (1 - k)
                c, r = int(x // TILE), int(y // TILE)
                if self.level.at(c, r) == "." and hgt >= 40:
                    self.level.rows[r][c] = "o"

    def hero_at(self, t):
        """Положение героя: x, высота над землёй, в воздухе ли, фаза прыжка."""
        portal_t = (self.portal_x - self.start_x) / self.speed + 0.8
        x = self.start_x + self.speed * max(0.0, t - 0.8)
        x = min(x, self.portal_x)
        lift, air, phase = 0.0, False, 0.0
        for (jx, dur, hgt) in self.jumps:
            jt = (x - jx) / self.speed
            if 0 <= jt <= dur:
                k = jt / dur
                lift = 4 * hgt * k * (1 - k)
                air, phase = True, k
        return x, lift, air, phase, portal_t

    def frame(self, t, dt=1 / FPS):
        from . import animator as A

        L = Layer(self.w, self.h)
        L.c[:] = self.sky.c
        x, lift, air, phase, portal_t = self.hero_at(t)
        cam_x = max(0.0, min(x - self.w * 0.36, self.level.w * TILE - self.w))
        cam_y = self.ground - self.h * 0.72
        stars(L, t, self.w, self.h, cam_x)
        moon(L, self.w, self.h, cam_x)
        compose(L, self.far, cam_x * 0.12)
        compose(L, self.clouds, cam_x * 0.22 + t * 4)
        compose(L, self.mid, cam_x * 0.45)
        # события: удар по блоку, монеты, пыль
        hy = self.ground - lift
        head_top = hy - HERO["height"] * 1.02
        col = int((x + 4) // TILE)
        for c in (col - 1, col, col + 1):
            for r in range(self.level.h):
                ch = self.level.at(c, r)
                cx, cy = c * TILE + 8, r * TILE + 8
                if ch == "?" and (c, r) not in self.level.bumped and air and abs(cx - x) < 12 and head_top <= (r + 1) * TILE + 3 and phase > 0.3:
                    self.level.bumped[(c, r)] = t
                    self.parts.add("score", cx, cy - 18, 0, -40, 0.8, text="+100")
                    self.parts.sparkle(cx, cy - 12, 10)
                    self.coins += 1
                    self.score += 100
                if ch == "o" and (c, r) not in self.level.taken and abs(cx - x) < 11 and head_top - 4 <= cy <= hy + 2:
                    self.level.taken[(c, r)] = t
                    self.parts.sparkle(cx, cy)
                    self.parts.add("score", cx, cy - 10, 0, -30, 0.6, text="+10")
                    self.coins += 1
                    self.score += 10
        if self.prev_air and not air:
            self.parts.dust(x, self.ground, 8)
        if not air and t > 0.8 and x < self.portal_x and t - self.last_step > 0.23:
            self.parts.dust(x - 4, self.ground, 2, dirx=1)
            self.last_step = t
        self.prev_air = air
        draw_tiles(L, self.level, cam_x, cam_y, t)
        # портал
        open_k = min(1.0, max(0.0, (t - 1.0) / 0.6))
        draw_portal(L, self.portal_x - cam_x, self.ground - cam_y, t, open_k)
        # герой
        sx, sy = x - cam_x, self.ground - cam_y - lift
        emotion = "happy" if t > portal_t - 0.6 or (air and phase > 0.4) else "neutral"
        if t < 0.8:
            pose, _ = A.action_pose("idle", t, 0.8)
            pose = A.pose_of("stand") if not isinstance(pose, dict) else pose
            emotion = "neutral"
        elif x >= self.portal_x:
            pose = A.pose_of("cheer")
            emotion = "happy"
        elif air:
            pose = A.mix(A.pose_of("stand"), {**A.pose_of("stand"), "sh1": 150, "el1": 20, "sh2": -40, "el2": 30,
                                                   "hip1": 70, "kn1": -95, "hip2": -10, "kn2": -40, "torso": -6}, min(1, phase * 2.4))
        else:
            pose, _ = A.action_pose("run", t, 10.0, speed=self.speed / HERO["height"])
        pose = dict(A.BASE, **pose)
        pose["dy"] = 0
        enter = max(0.0, t - (portal_t - 0.15))
        scale = max(0.0, 1 - enter / 0.5) if x >= self.portal_x else 1.0
        if scale > 0.02:
            draw_hero(L, pose, sx, sy, 1, emotion, t, scale=scale)
        if 0 < enter < 0.35:                                                     # вспышка в портале
            L.e += P["port3"] * (0.35 - enter) * 1.2
        self.parts.step(dt)
        self.parts.draw(L, cam_x, cam_y)
        draw_hud(L, self.coins, self.score, self.lives)
        if t > portal_t + 0.6:
            k = min(1.0, (t - portal_t - 0.6) / 0.4)
            y = int(self.h * 0.32 - (1 - k) * 20)
            draw_text(L, "УРОВЕНЬ", self.w // 2, y, 22, P["gold2"], emit=0.3)
            draw_text(L, "ПРОЙДЕН!", self.w // 2, y + 26, 22, P["gold2"], emit=0.3)
        return finish(L)


def render(out, w=216, h=384, secs=None, fps=FPS, scale=SCALE, crf=18):
    """Демо-ролик mp4 (вертикальный по умолчанию). Возвращает путь."""
    demo = Demo(w, h)
    portal_t = demo.hero_at(0)[4]
    secs = secs or portal_t + 2.4
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    from .studio import ffmpeg

    cmd = [ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "{}x{}".format(w * scale, h * scale),
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(secs * fps)
    for i in range(n):
        proc.stdin.write(upscale(demo.frame(i / fps, 1 / fps), scale).tobytes())
    proc.stdin.close()
    proc.wait()
    return out


def hero_sheet(out, cell=96, scale=4):
    """Лист героя: позы и эмоции — чтобы владелец сравнил с рисунком и сказал, что поправить."""
    from PIL import Image

    from . import animator as A

    rows = [("stand", "neutral", False), ("walk", "neutral", False), ("run", "happy", False), ("jump", "happy", False),
            ("cheer", "happy", True), ("think", "think", False), ("sad", "sad", False), ("surprised", "surprised", True),
            ("wave", "happy", True), ("point", "neutral", False), ("punch", "angry", False), ("sit", "neutral", False)]
    cols = 6
    W, H = cell * cols, cell * ((len(rows) + cols - 1) // cols)
    L = Layer(W, H)
    L.c[:] = P["sky1"]
    for i, (name, emo, front) in enumerate(rows):
        cx, cy = (i % cols) * cell + cell // 2, (i // cols) * cell + cell - 12
        L.c[cy:cy + 2, cx - cell // 2 + 6:cx + cell // 2 - 6] = P["grass1"]
        if name in A.POSES:
            pose = A.pose_of(name)
        else:
            pose, _ = A.action_pose(name, 0.35, 1.2)
            pose = dict(A.BASE, **pose)
        pose["dy"] = max(0.0, pose.get("dy", 0)) if name != "sit" else pose["dy"]
        draw_hero(L, pose, cx, cy, 1, emo, 0.5, front=front and name in A.FRONT)
    img = finish(L, vignette=False)
    Image.fromarray(upscale(img, scale)).save(out)
    return out


if __name__ == "__main__":          # python -m chloe.pixel_world [ролик.mp4] — демо-уровень и лист героя рядом
    import sys

    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "pixel-demo.mp4")
    print("ролик:", render(target))
    print("лист героя:", hero_sheet(target.with_name(target.stem + "-герой.png")))
