"""Героиня канала — отдельно от места. Рисунок Qwen по утверждённому образцу (assets/heroine/source.png, стоит прямо,
руки отведены) код режет на слои с шарнирами: ноги, туловище, голова с волосами, руки; моргание — дорисованные
веки. Движения задаёт код (поза по времени), рисунок не меняется — лицо и волосы всегда как на образце."""
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

SRC = Path(__file__).parent / "assets" / "heroine" / "source.png"
INK = (27, 33, 64)
# разметка source.png (928×1664): шарниры и области частей
PIVOT = {"head": (465, 615), "arm_l": (305, 700), "arm_r": (625, 700), "leg_l": (385, 1075), "leg_r": (545, 1075),
         "torso": (465, 1075)}
ARM_L = [(300, 640), (300, 835), (95, 930), (25, 905), (25, 820), (60, 790)]
ARM_R = [(625, 640), (625, 835), (835, 930), (905, 905), (905, 820), (870, 790)]
EYES = [(330, 450, 370, 490), (480, 600, 370, 490)]     # x0, x1, y0, y1
HEIGHT = 1292                                       # рост на source.png: макушка 168 → подошвы 1460
ORDER = ("leg_l", "leg_r", "torso", "head", "arm_l", "arm_r")
MOVES = ("idle", "wave", "jump", "walk", "dance")
SECONDS = {"idle": 1.5, "wave": 2.0, "jump": 1.6, "walk": 1.6, "dance": 2.0}


def _poly(shape, pts):
    import cv2

    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.array(pts, np.int32)], 1)
    return m.astype(bool)


def _fill_down(rgba, hole):
    """Дырка от руки в слое — дорисовать, протянув пряди/ткань снизу вверх и сверху вниз (по столбцам)."""
    out = rgba.copy()
    h = rgba.shape[0]
    for x in np.nonzero(hole.any(0))[0]:
        col = hole[:, x]
        ys = np.nonzero(col)[0]
        y0, y1 = ys.min(), ys.max()
        below = y1 + 1 if y1 + 1 < h and rgba[y1 + 1, x, 3] > 0 else None
        above = y0 - 1 if y0 > 0 and rgba[y0 - 1, x, 3] > 0 else None
        for y in ys:
            if below is not None and (above is None or y - y0 > (y1 - y0) / 2):
                out[y, x] = rgba[min(h - 1, below + (y1 - y) % 24), x]
            elif above is not None:
                out[y, x] = rgba[max(0, above - (y - y0) % 24), x]
    return out


def _eye_shape(a, x0, x1, y0, y1):
    import cv2

    c = a[y0:y1, x0:x1].astype(int)
    L = c[..., 0] * 0.3 + c[..., 1] * 0.59 + c[..., 2] * 0.11
    blue = c[..., 2] - c[..., 0] > 40
    dark = L < 90
    core = (blue | dark).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(core)
    if n < 2:
        return np.zeros(core.shape, bool)
    m = (lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    m = cv2.dilate(m, np.ones((5, 5), np.uint8))
    return m.astype(bool)


@lru_cache(maxsize=1)
def parts():
    """Слои героини: {имя: (rgba, (x0, y0))} в координатах source.png и кадры глаз для моргания."""
    import cv2
    from PIL import Image

    a = np.array(Image.open(SRC).convert("RGB"))
    h, w = a.shape[:2]
    fg = (np.abs(a.astype(int) - 255).max(-1) > 16).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg)
    fg = lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
    alpha = cv2.GaussianBlur(fg.astype(np.float32), (0, 0), 0.7)
    rgba = np.dstack([a, (alpha * 255).astype(np.uint8)])
    yy, xx = np.mgrid[0:h, 0:w]
    arm_l, arm_r = _poly((h, w), ARM_L) & fg, _poly((h, w), ARM_R) & fg
    grow = np.ones((11, 11), np.uint8)                                 # края рук (светлый ореол) — тоже рукам,
    arm_l = cv2.dilate(arm_l.astype(np.uint8), grow).astype(bool) & fg & (xx < 305)   # иначе при взмахе остаются обрывки
    arm_r = cv2.dilate(arm_r.astype(np.uint8), grow).astype(bool) & fg & (xx > 625)
    legs = fg & (yy >= 1075)
    leg_l, leg_r = legs & (xx < 465), legs & (xx >= 465)
    side_hair = ((xx < 305) | (xx > 625)) & (yy < 1010)
    head = fg & ((yy < 615) | side_hair) & ~arm_l & ~arm_r
    torso = fg & ~head & ~arm_l & ~arm_r & ~legs
    out = {}
    for name, m in (("leg_l", leg_l), ("leg_r", leg_r), ("torso", torso), ("head", head), ("arm_l", arm_l), ("arm_r", arm_r)):
        layer = rgba.copy()
        layer[~m, 3] = 0
        if name in ("head", "torso"):
            hole = (arm_l | arm_r) & ((head if name == "head" else torso) | _near(m, arm_l | arm_r))
            hole &= ~m
            filled = _fill_down(layer, hole & (layer[..., 3] == 0))
            filled[hole & (filled[..., 3] == 0), 3] = 0
            layer = filled
        out[name] = layer
    # моргание: веко цвета кожи по форме глаза и ресница дугой
    face = a[480:580, 340:590].reshape(-1, 3).astype(np.float32)        # цвет кожи — медиана телесных пикселей лица
    r, g, b = face[:, 0], face[:, 1], face[:, 2]
    skin = np.median(face[(r > 215) & (g > 170) & (b > 140) & (r - b > 25) & (r - b < 80) & (r - g < 45)], 0)
    lids = {}
    for kind in ("half", "closed"):
        head_l = out["head"].copy()
        for (x0, x1, y0, y1) in EYES:
            m = _eye_shape(a, x0, x1, y0, y1)
            ys, xs = np.nonzero(m)
            if not len(ys):
                continue
            top, bot, left, right = ys.min(), ys.max(), xs.min(), xs.max()
            cut = top + (bot - top) * (0.5 if kind == "half" else 1.0)
            sel = m & (np.arange(m.shape[0])[:, None] <= cut)
            reg = np.ascontiguousarray(head_l[y0:y1, x0:x1, :3])
            reg[sel] = skin
            base = cut if kind == "half" else top + (bot - top) * 0.6
            cx, half = (left + right) / 2, max(1.0, (right - left) / 2)
            pts = [(x, int(round(base + (8 * (1 - ((x - cx) / half) ** 2) if kind == "closed" else 0))))
                   for x in range(left, right + 1)]
            cv2.polylines(reg, [np.array(pts, np.int32)], False, INK, 6, cv2.LINE_AA)
            head_l[y0:y1, x0:x1, :3] = reg
        lids[kind] = head_l
    return out, lids


def _near(m, other):
    import cv2

    return cv2.dilate(m.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool) & other


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def plan(moves):
    """Движения по порядку и их времена: [(движение, начало, конец)], полная длина."""
    out, t = [], 0.0
    for m in [m for m in (moves or []) if m in SECONDS] or ["idle", "wave", "jump"]:
        out.append((m, t, t + SECONDS[m]))
        t += SECONDS[m]
    return out, t


def pose(t, steps):
    """Поза в момент t: углы частей (градусы, плюс — по часовой), сдвиг вверх (пиксели), сжатие, глаза."""
    P = {k: 0.0 for k in PIVOT}
    up, squash, legs_up = 0.0, 1.0, {"leg_l": 0.0, "leg_r": 0.0}
    P["head"] = 2.5 * math.sin(2 * math.pi * t / 3.0)
    P["arm_l"] = 2.0 * math.sin(2 * math.pi * t / 2.4)
    P["arm_r"] = -2.0 * math.sin(2 * math.pi * t / 2.4)
    breath = math.sin(2 * math.pi * t / 2.4)
    for m, a, b in steps:
        if not a <= t < b:
            continue
        d, u = t - a, (t - a) / (b - a)
        env = ease(u / 0.2) * ease((1 - u) / 0.2)
        if m == "wave":                                                 # правая рука вверх и машет, голова набок
            P["arm_r"] += (-78 + 16 * math.sin(2 * math.pi * d * 2.4)) * env   # наискось вверх наружу, лицо открыто
            P["head"] += 6 * env
        elif m == "jump":
            if d < 0.35:                                                # подготовка: присела, руки назад
                k = ease(d / 0.35)
                squash, up = 1 - 0.07 * k, -10 * k
                P["arm_l"] += 12 * k
                P["arm_r"] -= 12 * k
            elif d < 1.05:                                              # прыжок: руки вверх
                k = (d - 0.35) / 0.7
                up = 260 * 4 * k * (1 - k)
                squash = 1.04 if k < 0.5 else 1.0
                arms = 110 * ease(min(1, k * 3)) * (1 - ease((k - 0.7) / 0.3))
                P["arm_l"] += arms
                P["arm_r"] -= arms
            else:                                                       # приземление с пружинкой
                k = (d - 1.05) / 0.55
                squash = 1 - 0.07 * math.exp(-k * 4) * math.cos(k * 9)
        elif m == "walk":                                               # шаги на месте: ноги поочерёдно вверх
            ph = math.sin(2 * math.pi * d / 0.6)
            legs_up["leg_l"] = 40 * max(0.0, ph) * env
            legs_up["leg_r"] = 40 * max(0.0, -ph) * env
            P["arm_l"] += 10 * ph * env
            P["arm_r"] += 10 * ph * env
            up = 8 * abs(ph) * env
        elif m == "dance":                                              # качает корпусом, руки по очереди вверх
            ph = math.sin(2 * math.pi * d / 0.8)
            P["torso"] = 7 * ph * env
            P["head"] += 6 * ph * env
            P["arm_l"] += (100 if ph > 0 else 10) * env
            P["arm_r"] -= (10 if ph > 0 else 100) * env
            up = 18 * abs(math.sin(2 * math.pi * d / 0.4)) * env
    eyes = "open"
    for s in (1.1, 3.6, 3.95, 6.2):                                     # моргает
        e = t - s
        if 0 <= e < 0.07 or 0.2 <= e < 0.27:
            eyes = "half"
        elif 0.07 <= e < 0.2:
            eyes = "closed"
    return dict(angles=P, up=up, squash=squash * (1 + 0.006 * breath), legs_up=legs_up, eyes=eyes)


def render(t, steps, scale=1.0):
    """Кадр героини (RGBA float) в момент t; точка опоры — середина подошв, внизу по центру холста."""
    import cv2

    layers, lids = parts()
    p = pose(t, steps)
    h, w = layers["torso"].shape[:2]
    pad = 420
    H, W = h + pad, w + 2 * 200
    canvas = np.zeros((H, W, 4), np.float32)
    ox, oy = 200, pad                                                  # исходник лежит со сдвигом: место под прыжок
    foot = (465 + ox, 1460 + oy)
    sq = p["squash"]
    torso_pivot = (PIVOT["torso"][0] + ox, PIVOT["torso"][1] + oy - 0.0)

    def M_of(name):
        """Матрица части: своё вращение вокруг шарнира, потом за туловищем (голова, руки), потом прыжок и сжатие."""
        px, py = PIVOT[name][0] + ox, PIVOT[name][1] + oy
        own = cv2.getRotationMatrix2D((px, py), -p["angles"][name], 1.0)
        M = np.vstack([own, [0, 0, 1]])
        if name in ("head", "arm_l", "arm_r"):
            tor = np.vstack([cv2.getRotationMatrix2D(torso_pivot, -p["angles"]["torso"], 1.0), [0, 0, 1]])
            M = tor @ M
        if name in p["legs_up"]:
            M = np.array([[1, 0, 0], [0, 1, -p["legs_up"][name]], [0, 0, 1]]) @ M
        S = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float64)
        S[1, 1] = sq
        S[1, 2] = foot[1] * (1 - sq)                                    # сжатие к подошвам
        J = np.array([[1, 0, 0], [0, 1, -p["up"]], [0, 0, 1]])
        return (J @ S @ M)[:2]
    for name in ORDER:
        src = layers[name] if name != "head" or p["eyes"] == "open" else lids[p["eyes"]]
        big = np.zeros((H, W, 4), np.uint8)
        big[oy:oy + h, ox:ox + w] = src
        warped = cv2.warpAffine(big, M_of(name), (W, H), flags=cv2.INTER_LINEAR).astype(np.float32)
        a = warped[..., 3:] / 255
        canvas[..., :3] = canvas[..., :3] * (1 - a) + warped[..., :3] * a
        canvas[..., 3:] = canvas[..., 3:] * (1 - a) + 255 * a
    if scale != 1.0:
        canvas = cv2.resize(canvas, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA)
    return canvas, (foot[0] * scale, foot[1] * scale), p["up"] * scale
