"""План уровня-платформера без графики: где земля, где прыгать, когда собраны монеты и ударен блок.

Один и тот же план читают сцена в Blender (chloe/blender/voxel_level.py — расставляет кубики и ведёт героиню)
и сборка ролика (chloe/voxel_level.py — счёт, монеты и надписи поверх кадров), поэтому они не расходятся.
Только стандартная библиотека: модуль запускается и внутри Blender.

Единицы — плитки уровня (1 плитка = 1 кубик-блок). Героиня идёт по +X, земля — на высоте 0.
"""
import math

HERO_H = 2.6          # рост героини в плитках
SPEED = 4.2           # плиток в секунду
START = 2.5           # где стоит в начале
WAIT = 0.8            # секунд стоит, прежде чем побежать

DEMO = [(9, "coins", 3), (16, "block", 0), (24, "spikes", 2), (31, "coins", 2), (36, "gap", 3), (45, "pillar", 2),
        (50, "coins", 3), (56, "spikes", 3), (66, "portal", 0)]
DEMO_LEN = 74


class Plan:
    def __init__(self, features=None, length=None):
        self.features = sorted(features or DEMO)
        self.length = length or DEMO_LEN
        self.portal_x = next(c for c, k, _ in self.features if k == "portal") + 0.5
        self.block = [(c, k) for c, k, _ in self.features if k == "block"]
        self.block_z = HERO_H + 0.55                      # низ блока «?» — чуть выше макушки: под ним можно пройти
        self.jumps = self._jumps()
        self.coins = self._coins()
        self.portal_t = WAIT + (self.portal_x - START) / SPEED

    # --- земля и препятствия ---
    def gaps(self):
        return [(c, c + n) for c, k, n in self.features if k == "gap"]

    def solid(self, x):
        return not any(a <= x < b for a, b in self.gaps())

    def _jumps(self):
        out = []
        for col, kind, n in self.features:
            if kind in ("spikes", "gap", "pillar"):
                width = n if kind != "pillar" else 1
                run_up, land = 1.1, 1.4
                height = {"spikes": 1.7, "gap": 2.0, "pillar": n + 0.9}[kind]
                out.append((col - run_up, (run_up + width + land) / SPEED, height))
            elif kind == "block":                         # макушка упирается в низ блока на вершине прыжка
                length = 3.4
                out.append((col + 0.5 - length / 2, length / SPEED, self.block_z - HERO_H))
        return sorted(out)

    def _coins(self):
        """Монеты: ряды на высоте груди и дуги над ямами (их собирают в прыжке). [(x, z)]"""
        out = []
        for col, kind, n in self.features:
            if kind == "coins":
                out += [(c + 0.5, HERO_H * 0.55) for c in range(col, col + n)]
        for jx, dur, hgt in self.jumps:
            if hgt >= 2.0:
                length = dur * SPEED
                for k in (0.3, 0.5, 0.7):
                    out.append((jx + length * k, HERO_H * 0.55 + 4 * hgt * k * (1 - k)))
        return out

    # --- героиня ---
    def hero(self, t):
        """x, высота над землёй, в воздухе ли, фаза прыжка 0..1."""
        x = min(self.portal_x, START + SPEED * max(0.0, t - WAIT))
        for jx, dur, hgt in self.jumps:
            jt = (x - jx) / SPEED
            if 0 <= jt <= dur:
                k = jt / dur
                return x, 4 * hgt * k * (1 - k), True, k
        return x, 0.0, False, 0.0

    def events(self, fps, seconds):
        """По кадрам: собранные монеты (индексы), удар по блоку, счёт. [{coins, block_hit, score, new: [...]}]"""
        taken, hit_at, score, out = {}, None, 0, []
        for f in range(int(seconds * fps)):
            t = f / fps
            x, lift, air, ph = self.hero(t)
            new = []
            for i, (cx, cz) in enumerate(self.coins):
                if i not in taken and abs(cx - x) < 0.6 and lift - 0.2 <= cz <= lift + HERO_H + 0.2:
                    taken[i] = f
                    score += 10
                    new.append(("coin", i))
            for col, _ in self.block:
                if hit_at is None and air and ph > 0.3 and abs(col + 0.5 - x) < 0.7 and lift + HERO_H >= self.block_z - 0.08:
                    hit_at = f
                    score += 100
                    new.append(("block", col))
            out.append({"coins": len(taken) + (1 if hit_at is not None else 0), "score": score, "block_hit": hit_at,
                        "taken": dict(taken), "new": new})
        return out


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def smooth_cam(plan, t, lead=2.2, lag=0.35):
    """Камера чуть впереди героини и догоняет её плавно (без рывков на старте и у портала)."""
    acc, n = 0.0, 0
    for k in range(8):
        tt = max(0.0, t - lag * k / 8)
        acc += plan.hero(tt)[0]
        n += 1
    return acc / n + lead * ease((t - WAIT) / 1.0)


def bump(f_hit, f, fps):
    """Подскок блока после удара: 0..1..0 за 0.25 с."""
    if f_hit is None or f < f_hit:
        return 0.0
    d = (f - f_hit) / fps
    return math.sin(min(1.0, d / 0.25) * math.pi) if d < 0.25 else 0.0
