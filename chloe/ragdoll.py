"""Физика тела (ragdoll): от сильного удара стикмен падает по законам физики, а не по заготовке.

Тело — точки суставов, соединённые «костями» постоянной длины (метод Верле: положение, прошлое положение,
гравитация, потом несколько проходов «вернуть кости к своей длине»). Пол (панель задач) и края экрана — с отскоком
и трением, окна на рабочем столе — твёрдые препятствия. Удар — толчок в точке попадания: верх тела летит сильнее,
ноги отстают, поэтому тело переворачивается само.

Считается один раз при создании сцены (кадры по 1/200 с) — дальше это таблица положений и список ударов о пол
и стены (для звуков).
"""
import math

KEYS = ("hip", "neck", "head", "shoulder", "el1", "hand1", "el2", "hand2", "kn1", "foot1", "kn2", "foot2")
BONES = (("hip", "neck"), ("neck", "head"), ("shoulder", "el1"), ("el1", "hand1"), ("shoulder", "el2"), ("el2", "hand2"),
         ("hip", "kn1"), ("kn1", "foot1"), ("hip", "kn2"), ("kn2", "foot2"),
         ("hip", "shoulder"), ("shoulder", "neck"), ("hip", "head"))      # последние — держат корпус прямым
SOFT = {("hip", "head"): 0.6}                                             # насколько жёстко (1 — как кость)
MASS = {"hip": 3.0, "neck": 2.0, "shoulder": 2.0, "head": 1.5}            # тяжёлые точки меньше сдвигаются


def simulate(pts, push, ground, w, h, obstacles=(), secs=1.8, dt=1 / 200, gravity=2.6, size=100.0):
    """pts — суставы в момент удара {имя: (x, y)} (пиксели); push(имя) → (vx, vy) начальная скорость (пикс/с);
    obstacles — прямоугольники (x, y, ширина, высота). Возвращает {"frames": [(t, {имя: (x, y)})] каждые 0,02 с,
    "hits": [(t, "floor"|"wall"|"window", x, сила)], "rest": когда тело успокоилось}."""
    p = {k: [float(pts[k][0]), float(pts[k][1])] for k in KEYS}
    prev = {k: [p[k][0] - push(k)[0] * dt, p[k][1] - push(k)[1] * dt] for k in KEYS}
    rest_len = {b: math.dist(p[b[0]], p[b[1]]) for b in BONES}
    g = gravity * h
    radius = {k: (size * 0.095 if k == "head" else size * 0.02) for k in KEYS}
    frames, hits = [], []
    t, quiet, last_rec = 0.0, 0.0, -1.0
    touched = {}
    rest = secs
    while t < secs:
        moved = 0.0
        for k in KEYS:                                                   # шаг Верле с лёгким сопротивлением воздуха
            x, y = p[k]
            vx, vy = (x - prev[k][0]) * 0.998, (y - prev[k][1]) * 0.998
            prev[k] = [x, y]
            p[k] = [x + vx, y + vy + g * dt * dt]
            moved += abs(vx) + abs(vy)
        for _ in range(8):                                               # кости — обратно к своей длине
            for b in BONES:
                a, c = p[b[0]], p[b[1]]
                dx, dy = c[0] - a[0], c[1] - a[1]
                d = math.hypot(dx, dy) or 1e-6
                diff = (d - rest_len[b]) / d * SOFT.get(b, 1.0)
                ma, mc = MASS.get(b[0], 1.0), MASS.get(b[1], 1.0)
                ka, kc = mc / (ma + mc), ma / (ma + mc)
                a[0] += dx * diff * ka
                a[1] += dy * diff * ka
                c[0] -= dx * diff * kc
                c[1] -= dy * diff * kc
            for k in KEYS:                                               # пол, стены, окна
                rr = radius[k]
                x, y = p[k]
                vx, vy = x - prev[k][0], y - prev[k][1]
                hit = None
                if y > ground - rr:
                    p[k][1] = ground - rr
                    prev[k][1] = p[k][1] + vy * 0.3                      # отскок слабый
                    prev[k][0] = x - vx * 0.82                           # трение о пол
                    hit = ("floor", abs(vy) / dt)
                if x < rr or x > w - rr:
                    p[k][0] = min(max(x, rr), w - rr)
                    prev[k][0] = p[k][0] + vx * 0.5
                    hit = ("wall", abs(vx) / dt)
                for ox, oy, ow, oh in obstacles:
                    if ox - rr < p[k][0] < ox + ow + rr and oy - rr < p[k][1] < oy + oh + rr:
                        dl, dr = p[k][0] - (ox - rr), ox + ow + rr - p[k][0]   # вытолкнуть к ближнему краю
                        du, dd = p[k][1] - (oy - rr), oy + oh + rr - p[k][1]
                        m = min(dl, dr, du, dd)
                        if m == dl:
                            p[k][0] = ox - rr
                        elif m == dr:
                            p[k][0] = ox + ow + rr
                        elif m == du:
                            p[k][1] = oy - rr
                        else:
                            p[k][1] = oy + oh + rr
                        prev[k] = [p[k][0] + vx * 0.4, p[k][1] + vy * 0.4]
                        hit = ("window", math.hypot(vx, vy) / dt)
                if hit and hit[1] > h * 0.5 and t - touched.get((k, hit[0]), -1) > 0.25 and k in ("hip", "head", "shoulder"):
                    hits.append((round(t, 3), hit[0], p[k][0], hit[1] / h))
                if hit:
                    touched[(k, hit[0])] = t
        t += dt
        if t - last_rec >= 0.02 - 1e-9:
            frames.append((round(t, 3), {k: (p[k][0], p[k][1]) for k in KEYS}))
            last_rec = t
        quiet = quiet + dt if moved < size * 0.0006 * len(KEYS) else 0.0
        if quiet > 0.2 and t > 0.4:                                      # успокоилось
            rest = t
            break
    return {"frames": frames, "hits": hits, "rest": rest}


def sample(sim, dt):
    """Положение тела через dt секунд после удара (между записанными кадрами — линейно)."""
    fr = sim["frames"]
    if not fr:
        return None
    if dt <= fr[0][0]:
        return fr[0][1]
    if dt >= fr[-1][0]:
        return fr[-1][1]
    i = min(len(fr) - 2, int(dt / 0.02))
    while i > 0 and fr[i][0] > dt:
        i -= 1
    while i < len(fr) - 2 and fr[i + 1][0] < dt:
        i += 1
    (t0, a), (t1, b) = fr[i], fr[i + 1]
    k = (dt - t0) / max(t1 - t0, 1e-6)
    return {key: (a[key][0] + (b[key][0] - a[key][0]) * k, a[key][1] + (b[key][1] - a[key][1]) * k) for key in KEYS}


def push_for(size, d, h, power=1.0):
    """Толчок от удара: верх тела летит сильно назад и вверх, ноги — слабее (тело переворачивается)."""
    up = {"head": 1.0, "neck": 0.95, "shoulder": 0.9, "el1": 0.85, "el2": 0.85, "hand1": 0.8, "hand2": 0.8,
          "hip": 0.55, "kn1": 0.35, "kn2": 0.35, "foot1": 0.2, "foot2": 0.2}

    def push(k):
        return d * h * 1.25 * power * up[k], -h * 0.85 * power * up[k]
    return push
