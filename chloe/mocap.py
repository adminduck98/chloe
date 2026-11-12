"""Живые движения для стикменов: записи настоящих людей (захват движения) → углы суставов нашего скелета.

Данные: Carnegie Mellon University Graphics Lab Motion Capture Database (mocap.cs.cmu.edu), BVH-конверсия
Bruce Hahne (cgspeed.com). Условия CMU: бесплатно для исследований и коммерческих проектов, просят указать источник.

Как это работает:
- BVH — дерево суставов и по кадру углов на каждый; прямая кинематика даёт 3D-точки суставов.
- Вид сбоку: «вперёд» — куда в среднем смотрит человек за весь фрагмент, «вверх» — вверх; проекция на эту плоскость.
- 2D-точки → углы нашего скелета (animator.skeleton): 0 — вниз, плюс — вперёд; локоть и колено — относительно
  плеча и бедра; корпус — наклон от вертикали; высота таза (dy) и шаг вперёд — в долях роста героя.
Готовая библиотека движений лежит в chloe/data/moves.json (сюда — только для сборки её из BVH).
"""
import json
import math
import pathlib

import numpy as np

DATA = pathlib.Path(__file__).parent / "data" / "moves.json"
CREDIT = ("Motion capture: Carnegie Mellon University Graphics Lab Motion Capture Database (mocap.cs.cmu.edu), "
          "BVH conversion by B. Hahne (cgspeed.com)")


# --- BVH ---
def parse_bvh(text):
    """BVH → (суставы [{name, parent, offset, channels}], кадры (N × каналы), секунд на кадр)."""
    lines = iter(text.splitlines())
    joints, stack, cur = [], [], None
    for raw in lines:
        tok = raw.split()
        if not tok:
            continue
        if tok[0] in ("ROOT", "JOINT"):
            cur = {"name": tok[1], "parent": stack[-1] if stack else -1, "offset": None, "channels": []}
            joints.append(cur)
        elif tok[0] == "End":
            cur = {"name": "_end", "parent": stack[-1], "offset": None, "channels": [], "end": True}
            joints.append(cur)
        elif tok[0] == "{":
            stack.append(len(joints) - 1)
        elif tok[0] == "}":
            stack.pop()
        elif tok[0] == "OFFSET":
            cur["offset"] = np.array([float(v) for v in tok[1:4]])
        elif tok[0] == "CHANNELS":
            cur["channels"] = tok[2:2 + int(tok[1])]
        elif tok[0] == "MOTION":
            break
    n = int(next(lines).split()[-1])
    dt = float(next(lines).split()[-1])
    rows = [list(map(float, ln.split())) for ln in lines if ln.strip()]
    return joints, np.array(rows[:n]), dt


def _rot(axis, deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    m = np.zeros(a.shape + (3, 3))
    i = "XYZ".index(axis)
    j, k = [x for x in range(3) if x != i]
    m[..., i, i] = 1
    m[..., j, j] = c
    m[..., k, k] = c
    m[..., j, k] = -s
    m[..., k, j] = s
    return m


def positions(joints, frames):
    """Прямая кинематика: {сустав: (N × 3)} мировые координаты на каждом кадре."""
    n = len(frames)
    col = 0
    world_r, world_p, out = {}, {}, {}
    for idx, j in enumerate(joints):
        rot = np.broadcast_to(np.eye(3), (n, 3, 3)).copy()
        trans = np.zeros((n, 3))
        for ch in j["channels"]:
            v = frames[:, col]
            col += 1
            if ch.endswith("position"):
                trans[:, "XYZ".index(ch[0])] = v
            else:
                rot = rot @ _rot(ch[0], v)
        local_p = j["offset"] + (trans if j["parent"] == -1 else 0)
        if j["parent"] == -1:
            world_p[idx] = np.broadcast_to(local_p, (n, 3)).copy() if local_p.ndim == 1 else local_p
            world_r[idx] = rot
        else:
            pr, pp = world_r[j["parent"]], world_p[j["parent"]]
            world_p[idx] = pp + np.einsum("nij,j->ni", pr, j["offset"])
            world_r[idx] = pr @ rot
        if not j.get("end"):
            out[j["name"]] = world_p[idx]
    return out


# --- 3D → углы стикмена ---
MAP = {"hip": "Hips", "neck": "Neck1", "head": "Head",
       "sh1": "RightArm", "el1": "RightForeArm", "hand1": "RightHand",
       "sh2": "LeftArm", "el2": "LeftForeArm", "hand2": "LeftHand",
       "hip1": "RightUpLeg", "kn1": "RightLeg", "foot1": "RightFoot",
       "hip2": "LeftUpLeg", "kn2": "LeftLeg", "foot2": "LeftFoot"}
ALT = {"Neck1": ("Neck1", "Neck", "Spine1"), "Head": ("Head", "Neck1", "Neck")}


def _get(pos, name):
    for n in ALT.get(name, (name,)):
        if n in pos:
            return pos[n]
    raise KeyError(name)


def _ang(v_fwd, v_down):
    """Угол вектора: 0 — вниз, плюс — вперёд (градусы)."""
    return np.degrees(np.arctan2(v_fwd, v_down))


def _unwrap(a):
    return np.degrees(np.unwrap(np.radians(a)))


def _rel(a):
    """Разность углов → ближайшее значение (−180..180], потом без скачков во времени (сальто — дальше 180)."""
    return _unwrap((np.asarray(a) + 180) % 360 - 180)


def retarget(pos, leg_len=0.43, fps_in=120, fps_out=25, skip=1, view="follow"):
    """3D-точки суставов → покадровые углы нашего скелета и шаг вперёд.
    leg_len — бедро + голень нашего героя в долях роста. Возвращает {"poses": [...], "fwd": [...], "fps": fps_out}."""
    hips = _get(pos, "Hips")
    up = np.array([0.0, 1.0, 0.0])                                     # в CMU BVH вверх — Y
    across = _get(pos, "LeftUpLeg") - _get(pos, "RightUpLeg")          # слева направо (у человека)
    across[:, 1] = 0
    side = across.mean(axis=0)
    side /= np.linalg.norm(side) + 1e-9
    fwd = np.cross(side, up)                                           # куда смотрит (в среднем за фрагмент)
    fwd /= np.linalg.norm(fwd) + 1e-9
    step = max(1, int(round(fps_in / fps_out)))
    idx = np.arange(skip, len(hips), step)
    if view == "front":                                                # колесо, боковое сальто — смотрим спереди
        axes = np.broadcast_to(side, (len(idx), 3))
    elif view == "follow":                                             # взгляд «сбоку» поворачивается вместе с тазом
        k = max(1, int(fps_in * 0.3))
        sm = np.stack([np.convolve(across[:, i], np.ones(k) / k, mode="same") for i in range(3)], axis=1)
        sm = sm / (np.linalg.norm(sm, axis=1, keepdims=True) + 1e-9)
        f = np.cross(sm, up)
        f[(f @ fwd) < 0] *= 1                                          # направление — по тазу в каждый момент
        axes = f[idx]
    else:
        axes = np.broadcast_to(fwd, (len(idx), 3))

    def p2(name):
        p = _get(pos, MAP[name] if name in MAP else name)[idx]
        return np.einsum("ni,ni->n", p - hips[idx], axes) + (hips[idx] @ fwd), -(p @ up)   # вперёд, вниз

    P = {k: p2(k) for k in MAP}
    thigh = np.hypot(P["kn1"][0] - P["hip1"][0], P["kn1"][1] - P["hip1"][1]).mean()
    shin = np.hypot(P["foot1"][0] - P["kn1"][0], P["foot1"][1] - P["kn1"][1]).mean()
    scale = leg_len / (thigh + shin)                                    # единицы записи → доли роста героя

    def ang(a, b):
        return _unwrap(_ang(P[b][0] - P[a][0], P[b][1] - P[a][1]))

    torso_a = ang("hip", "neck")                                        # вверх по корпусу: около 180
    torso = _rel(180 - torso_a)
    out = {"torso": torso, "head": _rel(ang("neck", "head") - torso_a) * 0.5}
    for s in ("1", "2"):
        up_a, fore_a = ang("sh" + s, "el" + s), ang("el" + s, "hand" + s)
        out["sh" + s] = _rel(up_a - torso)                              # плечо — относительно корпуса
        out["el" + s] = _rel(fore_a - up_a)
        th_a, sh_a = ang("hip" + s, "kn" + s), ang("kn" + s, "foot" + s)
        out["hip" + s] = _rel(th_a)                                     # бедро — от вертикали
        out["kn" + s] = _rel(sh_a - th_a)
    floor = max(P[k][1].max() for k in ("foot1", "foot2", "kn1", "kn2", "hand1", "hand2"))   # пол — самая низкая точка тела
    hip_h = (floor - P["hip"][1]) * scale
    out["dy"] = hip_h - leg_len
    out["rot"] = np.zeros(len(idx))
    fwd_disp = (P["hip"][0] - P["hip"][0][0]) * scale
    poses = [{k: round(float(v[i]), 2) for k, v in out.items()} for i in range(len(idx))]
    return {"poses": poses, "fwd": [round(float(v), 4) for v in fwd_disp], "fps": fps_out}


def strikes(pos, limb="hand", fps_in=120, fps_out=25):
    """Кадры, где рука (или нога) дальше всего от корпуса вперёд — моменты ударов (для звука и вспышки), в секундах."""
    hips = _get(pos, "Hips")
    out = []
    for side in ("Right", "Left"):
        end = _get(pos, side + ("Hand" if limb == "hand" else "Foot"))
        rel = end - hips if limb == "hand" else end - _get(pos, side + "UpLeg")
        d = np.linalg.norm(rel[:, [0, 2]] if limb == "hand" else rel * np.array([1.0, -1.0, 1.0]) + [0, 0, 0], axis=1)
        if limb == "foot":                                             # пинок: стопа выше всего относительно бедра
            d = rel[:, 1] - rel[:, 1].min()
        step = max(1, int(round(fps_in / fps_out)))
        d = d[::step]
        thr = d.min() + (d.max() - d.min()) * 0.7 if limb == "foot" else np.percentile(d, 85)
        for i in range(1, len(d) - 1):
            if d[i] >= thr and d[i] >= d[i - 1] and d[i] >= d[i + 1] and (limb == "foot" or d[i] > d.mean() * 1.15):
                if all(abs(i / fps_out - t) > 0.25 for t in out):
                    out.append(round(i / fps_out, 2))
    return sorted(out)


# --- готовая библиотека ---
_lib = None


def library():
    global _lib
    if _lib is None:
        try:
            _lib = json.loads(DATA.read_text(encoding="utf-8"))["moves"]
        except (OSError, ValueError, KeyError):
            _lib = {}
    return _lib


def pose_at(name, t, dur):
    """Поза движения name из записи через t секунд (длительность в сцене dur): (поза, шаг вперёд в долях роста).
    Короткую запись в длинном отрезке повторяем (если она «петлёй»), иначе держим последний кадр."""
    m = library().get(name)
    if not m:
        return None
    n = len(m["poses"])
    i = t * m["fps"]
    if name in REPEAT and i >= n:                    # повтор удара — с начала
        i = i % n
    if m.get("loop"):
        laps = int(i // n)
        i = i % n
        base = m["fwd"][-1] * laps
    else:
        i = min(i, n - 1)
        base = 0.0
    a, k = int(i), i - int(i)
    b = min(a + 1, n - 1) if not m.get("loop") else (a + 1) % n
    pa, pb = m["poses"][a], m["poses"][b]
    pose = {key: pa[key] + (pb[key] - pa[key]) * k for key in pa}
    fwd = base + m["fwd"][a] + (m["fwd"][b] - m["fwd"][a]) * k if b > a or not m.get("loop") else base + m["fwd"][a]
    return pose, fwd


# --- сборка библиотеки из BVH (один раз; результат — chloe/data/moves.json) ---
# имя движения → (файл, вид: loop — цикл шага | strike — удар (рука/нога) | burst — от начала движения до остановки,
#                 откуда искать (с), докуда (с))
SELECTION = {
    "walk": ("02/02_01.bvh", "loop", 0.5, 4.0), "run": ("09/09_01.bvh", "loop", 0.3, 2.5),
    "jump": ("13/13_11.bvh", "burst", 0.0, 4.0),
    "punch": ("14/14_01.bvh", "strike_hand", 2.0, 8.0),
    "kick": ("135/135_04.bvh", "strike_foot", 6.0, 7.5), "jumpkick": ("90/90_05.bvh", "burst", 0.0, 6.0),
    "spinkick": ("88/88_06.bvh", "burst", 0.0, 6.0), "backflip": ("90/90_01.bvh", "burst", 1.8, 6.0),
    "sideflip": ("90/90_08.bvh", "burst_front", 0.0, 6.0), "cartwheel": ("87/87_05.bvh", "burst_front", 0.0, 6.0),
    "faceplant": ("90/90_16.bvh", "burst", 0.0, 6.0), "slip": ("90/90_17.bvh", "burst", 0.0, 6.0),
    "rugpull": ("90/90_18.bvh", "burst", 0.0, 6.0),
    # уклоны, подкат, лазание, ползание, кувырок, танцы — отрезки выбраны по раскадровке записей
    "duck": ("134/134_01.bvh", "clip", 1.1, 2.8), "slide": ("131/131_05.bvh", "clip", 4.3, 7.5),
    "climb": ("13/13_33.bvh", "clip", 1.0, 6.0),
    "roll": ("90/90_33.bvh", "clip", 2.4, 5.0), "breakdance": ("90/90_28.bvh", "clip", 1.8, 6.0),
    "kazachok": ("90/90_30.bvh", "clip", 4.2, 9.0), "moonwalk": ("90/90_32.bvh", "clip", 2.0, 5.8),
    "ballet": ("05/05_02.bvh", "clip", 3.0, 7.0),
}
FACE_FORWARD = ()               # низкие движения головой вперёд (подкат — ногами вперёд, его не трогаем); ползание из
                                # записи 133_01 убрано — в ней суставы переворачиваются, ползание остаётся по формулам
DODGE = ("duck", "slide", "roll", "crawl", "backflip", "sideflip", "cartwheel", "jump")   # в этих движениях удар проходит мимо


def despike(pos, fps, win=0.08):
    """Медианный фильтр по времени (окно win секунд) для каждого сустава: в CMU-записях суставы иногда на несколько
    кадров «переворачиваются» — фильтр убирает такие одиночные выбросы, не сглаживая быстрые удары."""
    k = max(3, int(fps * win) | 1)
    h = k // 2
    out = {}
    for name, v in pos.items():
        pad = np.concatenate([np.repeat(v[:1], h, axis=0), v, np.repeat(v[-1:], h, axis=0)])
        win_ = np.lib.stride_tricks.sliding_window_view(pad, k, axis=0)       # (N, 3, k)
        out[name] = np.median(win_, axis=-1)
    return out


def _slice(pos, a, b):
    return {k: v[a:b] for k, v in pos.items()}


def _activity(pos, fps):
    """Насколько быстро движется тело в каждый кадр (сумма скоростей суставов)."""
    keys = [k for k in ("Hips", "RightHand", "LeftHand", "RightFoot", "LeftFoot", "Head") if k in pos]
    v = sum(np.linalg.norm(np.diff(pos[k], axis=0), axis=1) for k in keys) * fps
    k = max(1, int(fps * 0.1))
    return np.convolve(np.concatenate([[v[0]], v]), np.ones(k) / k, mode="same")


def _cycle(pos, fps, a, b):
    """Один цикл шага (правая стопа: от одного её «самого переднего» положения до следующего) в окне [a, b)."""
    hips, foot = pos["Hips"][a:b], pos["RightFoot"][a:b]
    rel = foot - hips
    d = rel[:, [0, 2]]
    walk = hips[-1] - hips[0]
    walk = walk[[0, 2]] / (np.linalg.norm(walk[[0, 2]]) + 1e-9)
    s = d @ walk
    peaks = [i for i in range(1, len(s) - 1) if s[i] >= s[i - 1] and s[i] > s[i + 1] and s[i] > np.percentile(s, 70)]
    peaks = [p for i, p in enumerate(peaks) if i == 0 or p - peaks[i - 1] > fps * 0.4]
    if len(peaks) < 3:
        return a, b
    mid = len(peaks) // 2
    return a + peaks[mid - 1], a + peaks[mid]


def build(raw_dir, out=DATA, fps_out=25):
    """Собрать библиотеку движений из скачанных BVH (SELECTION) → JSON. Возвращает отчёт {имя: секунды}."""
    raw_dir = pathlib.Path(raw_dir)
    moves, report = {}, {}
    for name, (f, kind, t0, t1) in SELECTION.items():
        joints, frames, dt = parse_bvh((raw_dir / f).read_text())
        fps = round(1 / dt)
        pos = despike(positions(joints, frames), fps)
        a, b = max(1, int(t0 * fps)), min(len(frames), int(t1 * fps))
        hits = []
        if kind.startswith("clip"):
            pass                                                  # отрезок выбран вручную
        elif kind == "loop":
            a, b = _cycle(pos, fps, a, b)
        elif kind.startswith("strike"):
            limb = kind.split("_")[1]                        # strike_hand | strike_foot | strike_foot_front
            w = _slice(pos, a, b)
            peaks = strikes(w, limb, fps, fps_out)
            if peaks:                                           # первый явный удар: замах до него, отдача после
                p = a + int(peaks[0] * fps)
                a, b = max(1, p - int(0.7 * fps)), min(len(frames), p + int(0.6 * fps))
        else:
            act = _activity(pos, fps)[a:b]
            calm = np.median(act)
            hot = np.where(act > calm + (act.max() - calm) * 0.2)[0]       # начало — как только тело зашевелилось
            if len(hot):
                a, b = a + max(0, hot[0] - int(0.5 * fps)), min(len(frames), a + hot[-1] + int(0.45 * fps))
        w = _slice(pos, a, b)
        view = "front" if kind.endswith("front") else "fixed" if kind.endswith("fixed") else "follow"
        r = retarget(w, fps_in=fps, fps_out=fps_out, skip=0, view=view)
        if kind.startswith("strike"):
            hits = strikes(w, kind.split("_")[1], fps, fps_out)[:1]
        elif "kick" in name:                                   # пинок в прыжке, с разворота — момент, где нога выше всего
            hits = strikes(w, "foot", fps, fps_out)[:1]
        lands = landings(w, fps, fps_out)
        if name in FACE_FORWARD:
            r = face_forward(r)
        moves[name] = dict(r, loop=kind.startswith("loop") or kind.startswith("clip_loop"), hits=hits, lands=lands, src=f)
        report[name] = round(len(r["poses"]) / fps_out, 2)
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(json.dumps({"credit": CREDIT, "moves": moves}, ensure_ascii=False, separators=(",", ":")),
                                 encoding="utf-8")
    global _lib
    _lib = None
    return report


def face_forward(r):
    """Низкое движение (ползёт, лежит) с головой позади таза — зеркалим: у лежачего тела «вперёд» по тазу выходит наоборот.
    Зеркало: все углы и шаг меняют знак."""
    tilt = [(p["torso"] + 180) % 360 - 180 for p in r["poses"]]        # наклон корпуса в −180..180
    low = [a for a in tilt if abs(a) > 45]
    if len(low) < len(r["poses"]) * 0.5:
        return r
    behind = sum(1 for a in low if a < 0) / len(low)                   # корпус наклонён назад — голова за тазом
    if behind < 0.5:
        return r
    keys = ("torso", "head", "sh1", "el1", "sh2", "el2", "hip1", "kn1", "hip2", "kn2")
    r = dict(r)
    r["poses"] = [{k: (-v if k in keys else v) for k, v in p.items()} for p in r["poses"]]
    r["fwd"] = [-v for v in r["fwd"]]
    return r


def landings(pos, fps_in, fps_out=25):
    """Когда тело приземлилось: самая низкая точка тела резко перестала падать после полёта или кувырка (секунды)."""
    keys = [k for k in ("RightFoot", "LeftFoot", "RightHand", "LeftHand", "Head", "Hips") if k in pos]
    low = np.min(np.stack([pos[k][:, 1] for k in keys]), axis=0)
    hips = pos["Hips"][:, 1]
    step = max(1, int(round(fps_in / fps_out)))
    low, hips = low[::step], hips[::step]
    floor = np.percentile(low, 5)
    air = low > floor + (hips.max() - floor) * 0.12
    out = []
    for i in range(1, len(air)):
        if air[i - 1] and not air[i] and all(abs(i / fps_out - t) > 0.4 for t in out):
            out.append(round(i / fps_out, 2))
    vel = np.diff(hips) * fps_out                                  # упал (таз резко опустился и остановился)
    for i in range(2, len(vel)):
        if vel[i - 1] < -(hips.max() - floor) * 2.5 and vel[i] > vel[i - 1] * 0.3 and all(abs(i / fps_out - t) > 0.4 for t in out):
            out.append(round(i / fps_out, 2))
    return sorted(out)


NATURAL = {}


def speed(name):
    """Естественная скорость шага записи (долей роста в секунду) — для подгонки ходьбы и бега под путь в сцене."""
    m = library().get(name)
    if not m or not m.get("loop"):
        return 0.0
    return abs(m["fwd"][-1]) / (len(m["poses"]) / m["fps"])


def duration(name):
    m = library().get(name)
    return len(m["poses"]) / m["fps"] if m else 0.0


REPEAT = ("punch", "kick", "breakdance", "kazachok", "moonwalk", "ballet")   # в длинном отрезке повторяются, а не замирают


def reps(name, dur):
    """Сколько раз повторить удар в отрезке dur (разовые движения — один раз)."""
    if name not in REPEAT or not library().get(name):
        return 1
    return max(1, int(round(dur / duration(name))))


def rate_for(name, dur, need_speed=None):
    """Во сколько раз ускорить запись: петля — под нужную скорость шага; разовое движение — чтобы уложиться в отрезок."""
    m = library().get(name)
    if not m:
        return 1.0
    if m.get("loop"):
        nat = speed(name)
        return max(0.6, min(1.8, need_speed / nat)) if need_speed and nat else 1.0
    n = reps(name, dur)
    return max(1.0 if n == 1 else 0.8, min(1.8, n * duration(name) / max(dur, 0.05)))


def hits_in(name, dur):
    """Моменты ударов в отрезке dur (секунды от начала отрезка) с учётом повторов и ускорения."""
    m = library().get(name)
    if not m or not m["hits"]:
        return []
    r, n, ln = rate_for(name, dur), reps(name, dur), duration(name)
    return [(k * ln + h) / r for k in range(n) for h in m["hits"] if (k * ln + h) / r < dur]


def lands_in(name, dur):
    m = library().get(name)
    if not m:
        return []
    r = rate_for(name, dur)
    return [x / r for x in m["lands"] if x / r < dur]


def fwd_at(name, t_move):
    """Насколько тело сдвинулось вперёд к моменту t_move записи (доли роста)."""
    m = library().get(name)
    if not m:
        return 0.0
    i = min(len(m["fwd"]) - 1, int(t_move * m["fps"]))
    return m["fwd"][i]
