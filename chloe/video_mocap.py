"""Своя хореография: видео с телефона → движение стикмена (захват движения по видео).

Человек снимает себя (лучше сбоку, во весь рост, на ровном фоне, 3–15 секунд). MediaPipe Pose (Google, на процессоре)
находит на каждом кадре 33 точки тела; из них берутся наши суставы (таз, шея, голова, плечи, локти, кисти, бёдра,
колени, стопы), и дальше — тот же перенос на стикмена, что для записей CMU (mocap.angles_2d): углы суставов,
высота таза, шаг вперёд. Движение сохраняется в личную библиотеку (~/.chloe/moves_user.json) под своим именем и сразу
доступно в мультфильмах, в том числе с мультяшным фильтром.

Видео не уходит в интернет: всё считается на этом компьютере. Модель позы (~9 МБ) скачивается один раз в ~/.chloe/models.
"""
import json
import math
import pathlib
import subprocess

import numpy as np

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/"
             "pose_landmarker_full.task")
# точки MediaPipe Pose → наши суставы (правая сторона — «1», левая — «2»; mid — середина двух точек)
LM = {"hip": ("mid", 23, 24), "neck": ("mid", 11, 12), "head": ("mid", 7, 8),
      "sh1": 12, "el1": 14, "hand1": 16, "sh2": 11, "el2": 13, "hand2": 15,
      "hip1": 24, "kn1": 26, "foot1": 28, "hip2": 23, "kn2": 25, "foot2": 27,
      "fi1": ("mid", 18, 20), "fi2": ("mid", 17, 19),               # кисть: середина мизинца и указательного
      "toe1": 32, "toe2": 31}                                       # носки стоп
BODY = ("neck", "head", "sh1", "sh2", "el1", "el2", "hand1", "hand2", "fi1", "fi2", "hip1", "hip2", "kn1", "kn2",
        "foot1", "foot2", "toe1", "toe2")                           # точки тела «как снято» (для объёмного стикмена)


class VideoMocapError(Exception):
    pass


def model_path():
    from .config import DATA

    return DATA / "models" / "pose_landmarker_full.task"


def ensure_model():
    """Модель позы: один раз скачать с серверов Google (MediaPipe), дальше — с диска."""
    import urllib.request

    p = model_path()
    if p.exists() and p.stat().st_size > 1_000_000:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=120) as r, open(tmp, "wb") as f:
            f.write(r.read())
    except OSError as e:
        raise VideoMocapError("не скачалась модель позы: {}".format(e)) from None
    tmp.replace(p)
    return p


def frames(video, fps=25, width=640):
    """Кадры видео (RGB, уменьшенные до width) по fps в секунду — через ffmpeg, без OpenCV."""
    from . import studio

    probe = subprocess.run([studio.ffmpeg(), "-hide_banner", "-i", str(video)], capture_output=True, text=True)
    import re

    m = re.search(r", (\d{2,5})x(\d{2,5})", probe.stderr)
    if not m:
        raise VideoMocapError("не читается видео")
    w0, h0 = int(m.group(1)), int(m.group(2))
    rot = re.search(r"rotate\s*:\s*(-?\d+)|displaymatrix: rotation of (-?[\d.]+)", probe.stderr)
    if rot and abs(float(rot.group(1) or rot.group(2))) in (90.0, 270.0):
        w0, h0 = h0, w0                                               # телефон снимал вертикально
    h = int(round(h0 * width / w0 / 2) * 2)
    r = subprocess.run([studio.ffmpeg(), "-v", "error", "-i", str(video), "-vf", "fps={},scale={}:{}".format(fps, width, h),
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=600)
    data = np.frombuffer(r.stdout, dtype=np.uint8)
    n = len(data) // (width * h * 3)
    if n < 5:
        raise VideoMocapError("в видео меньше 5 кадров")
    return data[:n * width * h * 3].reshape(n, h, width, 3), (width, h)


def landmarks(video, fps=25, world=False):
    """Точки тела на каждом кадре: массив (кадры × 33 × 4: x, y в пикселях кадра, видимость, глубина z — меньше значит
    ближе к камере, в тех же пикселях) и размер кадра."""
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
    except ImportError:
        raise VideoMocapError("не установлен MediaPipe (pip install mediapipe)") from None
    imgs, (w, h) = frames(video, fps)
    opts = vision.PoseLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=str(ensure_model())),
                                        running_mode=vision.RunningMode.VIDEO, num_poses=1)
    out = np.full((len(imgs), 33, 4), np.nan)
    w3 = np.full((len(imgs), 33, 3), np.nan)                  # 3D-скелет в метрах: x вправо, y вниз, z — от камеры
    with vision.PoseLandmarker.create_from_options(opts) as det:
        for i, img in enumerate(imgs):
            res = det.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img)),
                                       int(i * 1000 / fps))
            if res.pose_landmarks:
                for j, lm in enumerate(res.pose_landmarks[0]):
                    out[i, j] = (lm.x * w, lm.y * h, getattr(lm, "visibility", 1.0) or 1.0, (lm.z or 0.0) * w)
            if getattr(res, "pose_world_landmarks", None):
                for j, lm in enumerate(res.pose_world_landmarks[0]):
                    w3[i, j] = (lm.x, lm.y, lm.z)
    return (out, (w, h), w3) if world else (out, (w, h))


def smooth3d(w3, sigma=1.2):
    """3D-скелет без пропусков и дрожания: пустые кадры — по соседним, потом медиана по 3 кадрам и мягкое сглаживание
    (глубина у MediaPipe дрожит сильнее всего)."""
    w3 = w3.copy()
    n = len(w3)
    idx = np.arange(n)
    for j in range(w3.shape[1]):
        good = ~np.isnan(w3[:, j, 0])
        if not good.any():
            w3[:, j] = 0.0
            continue
        for c in range(3):
            w3[~good, j, c] = np.interp(idx[~good], idx[good], w3[good, j, c])
    med = w3.copy()
    for i in range(n):
        med[i] = np.median(w3[max(0, i - 1):i + 2], axis=0)
    k = int(sigma * 3)
    if k and n > 2:
        g = np.exp(-0.5 * (np.arange(-k, k + 1) / sigma) ** 2)
        g /= g.sum()
        pad = np.pad(med, ((k, k), (0, 0), (0, 0)), mode="edge")
        med = np.stack([np.tensordot(g, pad[i:i + 2 * k + 1], axes=(0, 0)) for i in range(n)])
    return med


def body3d(w3, mirror=False):
    """3D-тело для мультипликатора: точки относительно середины таза в долях роста стикмена (x вправо, y вниз, z — от
    камеры) и куда смотрит человек (угол в плоскости пола, градусы: 0 — вправо, −90 — на камеру)."""
    from . import animator as A

    sign = -1.0 if mirror else 1.0

    def get(spec):
        if isinstance(spec, tuple):
            return (w3[:, spec[1]] + w3[:, spec[2]]) / 2
        return w3[:, spec]
    P = {k: get(v) * np.array([sign, 1.0, 1.0]) for k, v in LM.items()}
    hip = P["hip"]
    leg = float(np.median(np.linalg.norm(P["kn1"] - P["hip1"], axis=1) + np.linalg.norm(P["foot1"] - P["kn1"], axis=1))) or 1.0
    s = (A.SEG["thigh"] + A.SEG["shin"]) / leg
    across = (P["hip2"] - P["hip1"]).mean(axis=0)                 # справа налево (у человека)
    fwd = np.array([across[2], 0.0, -across[0]])                  # перпендикуляр в плоскости пола
    nose = (w3[:, 0] * np.array([sign, 1.0, 1.0]) - hip).mean(axis=0)
    if fwd @ nose < 0:
        fwd = -fwd
    face = float(np.degrees(np.arctan2(fwd[2], fwd[0])))
    frames = [{k: [round(float(v), 4) for v in (P[k][i] - hip[i]) * s] for k in BODY if k in P} for i in range(len(w3))]
    return frames, round(face, 1)


def fill_gaps(pts, min_vis=0.4):
    """Кадры, где человек не нашёлся или точка невидима, — заполнить по соседним (линейно), края — ближайшим."""
    pts = pts.copy()
    n = len(pts)
    for j in range(pts.shape[1]):
        bad = np.isnan(pts[:, j, 0]) | (pts[:, j, 2] < min_vis)
        if (~bad).sum() < max(2, n * 0.2):                  # точка почти всё время закрыта (дальняя рука сбоку) —
            bad = np.isnan(pts[:, j, 0])                    # берём, что есть, хоть и неуверенно
        good = np.where(~bad)[0]
        if len(good) == 0:
            continue
        for c in (0, 1, 3)[:pts.shape[2] - 1]:                  # x, y и глубина (если есть)
            pts[bad, j, c] = np.interp(np.where(bad)[0], good, pts[good, j, c])
        pts[bad, j, 2] = min_vis
    if np.isnan(pts[:, 23, 0]).all():
        raise VideoMocapError("на видео не нашёлся человек во весь рост")
    return pts


def smooth(pts, k=3):
    """Убрать дрожание точек: скользящее среднее по k кадрам (медиана — против одиночных выбросов)."""
    n = len(pts)
    out = pts.copy()
    h = k // 2
    for i in range(n):
        a, b = max(0, i - h), min(n, i + h + 1)
        out[i, :, :2] = np.median(pts[a:b, :, :2], axis=0)
        if pts.shape[2] > 3:
            out[i, :, 3] = np.median(pts[a:b, :, 3], axis=0)
    return out


def faces_left(pts):
    """Куда смотрит человек: нос левее середины ушей на большинстве кадров — влево."""
    nose, ears = pts[:, 0, 0], (pts[:, 7, 0] + pts[:, 8, 0]) / 2
    d = nose - ears
    d = d[np.isfinite(d)]
    return bool(len(d)) and float(np.median(d)) < 0


def to_move(pts, fps=25, mirror=None, world=None):
    """Точки тела (пиксели, y вниз) → движение стикмена: {"poses", "fwd", "fps", "loop", "hits", "lands"}.
    mirror — человек на видео смотрит влево (тогда отражаем, чтобы «вперёд» было вправо); None — понять самому."""
    from . import mocap as MC

    def get(spec):
        if isinstance(spec, tuple):
            return (pts[:, spec[1], :2] + pts[:, spec[2], :2]) / 2
        return pts[:, spec, :2]

    if mirror is None:
        mirror = faces_left(pts)
    sign = -1.0 if mirror else 1.0
    P = {k: (get(v)[:, 0] * sign, get(v)[:, 1]) for k, v in LM.items()}
    r = MC.angles_2d(P, fps)
    fit_limbs(r["poses"], P)
    r["body"] = body_frames(P, pts)
    if world is not None and len(world) == len(pts):             # настоящий 3D-скелет — героя можно поворачивать
        r["body3d"], r["face3d"] = body3d(smooth3d(world), mirror)
    r.update(loop=False, hits=hits(P, pts[:, :, 2], fps), lands=[], src="video")
    return r


def body_frames(P, pts):
    """Тело «как снято»: на каждом кадре точки относительно середины таза в долях роста стикмена (x — вперёд, y — вниз)
    и какая сторона ближе к камере ("n": 1 — правая, 2 — левая; по глубине плеч и бёдер). Объёмный стикмен рисуется
    прямо по ним: два плеча, два бедра, кисти и стопы — как у человека, даже если снято вполоборота."""
    from . import animator as A

    seg = A.SEG
    leg_px = float(np.median(np.hypot(P["kn1"][0] - P["hip1"][0], P["kn1"][1] - P["hip1"][1])
                             + np.hypot(P["foot1"][0] - P["kn1"][0], P["foot1"][1] - P["kn1"][1]))) or 1.0
    s = (seg["thigh"] + seg["shin"]) / leg_px
    depth = pts.shape[2] > 3
    out = []
    for i in range(len(P["hip"][0])):
        hx, hy = P["hip"][0][i], P["hip"][1][i]
        fr = {k: [round(float((P[k][0][i] - hx) * s), 4), round(float((P[k][1][i] - hy) * s), 4)] for k in BODY if k in P}
        if depth:
            right = pts[i, 12, 3] + pts[i, 24, 3]
            left = pts[i, 11, 3] + pts[i, 23, 3]
            fr["n"] = 1 if right <= left else 2
        else:
            fr["n"] = 1
        out.append(fr)
    return out


def _two_bone(root, target, a, b, hint):
    """Две кости длиной a и b от root к target (обратная кинематика): где сустав посередине. Из двух решений —
    ближнее к hint (сустав на видео); не дотягивается — прямо к цели."""
    dx, dy = target[0] - root[0], target[1] - root[1]
    d = math.hypot(dx, dy) or 1e-6
    ux, uy = dx / d, dy / d
    dd = min(max(d, abs(a - b) + 1e-4), a + b - 1e-4)
    cos_al = max(-1.0, min(1.0, (a * a + dd * dd - b * b) / (2 * a * dd)))
    al = math.acos(cos_al)
    best = None
    for sgn in (1, -1):
        ca, sa = math.cos(al * sgn), math.sin(al * sgn)
        jx, jy = root[0] + a * (ux * ca - uy * sa), root[1] + a * (ux * sa + uy * ca)
        dist = math.hypot(jx - hint[0], jy - hint[1])
        if best is None or dist < best[0]:
            best = (dist, (jx, jy))
    return best[1]


def _ang(v):
    """Угол вектора (вперёд, вниз) от вертикали вниз, плюс — вперёд (градусы), как в mocap."""
    return math.degrees(math.atan2(v[0], v[1]))


def fit_limbs(poses, P):
    """Углы рук и ног — так, чтобы кисти и стопы стикмена встали туда же, где у человека на видео, и кисть повёрнута
    так же (wr — по указательному пальцу и мизинцу) (относительно таза,
    в масштабе стикмена), а локти и колени согнулись в ту же сторону. Иначе у стикмена одна точка плеча на позвоночнике
    и одна точка таза, а у человека два плеча и два бедра в стороны (особенно снято вполоборота): углы те же, а руки
    мимо автомата и стойка уже."""
    from . import animator as A
    from . import mocap as MC

    seg = A.SEG
    leg_px = float(np.median(np.hypot(P["kn1"][0] - P["hip1"][0], P["kn1"][1] - P["hip1"][1])
                             + np.hypot(P["foot1"][0] - P["kn1"][0], P["foot1"][1] - P["kn1"][1]))) or 1.0
    s = (seg["thigh"] + seg["shin"]) / leg_px
    n = len(poses)
    out = {k: [] for k in ("sh1", "el1", "sh2", "el2", "hip1", "kn1", "hip2", "kn2", "wr1", "wr2")}
    for i in range(n):
        hx, hy = P["hip"][0][i], P["hip"][1][i]

        def rel(name):
            return ((P[name][0][i] - hx) * s, (P[name][1][i] - hy) * s)
        tor = math.radians(poses[i]["torso"])
        sh = (math.sin(tor) * seg["torso"] * 0.84, -math.cos(tor) * seg["torso"] * 0.84)   # плечо стикмена
        for side in ("1", "2"):
            el = _two_bone(sh, rel("hand" + side), seg["upper"], seg["fore"], rel("el" + side))
            hand = rel("hand" + side)
            up_a = _ang((el[0] - sh[0], el[1] - sh[1]))
            fore_a = _ang((hand[0] - el[0], hand[1] - el[1]))
            out["sh" + side].append(up_a - poses[i]["torso"])
            out["el" + side].append(fore_a - up_a)
            fi = rel("fi" + side)                                     # кисть: куда смотрят костяшки на видео
            out["wr" + side].append(_ang((fi[0] - hand[0], fi[1] - hand[1])) - fore_a if "fi" + side in P else 0.0)
            kn = _two_bone((0.0, 0.0), rel("foot" + side), seg["thigh"], seg["shin"], rel("kn" + side))
            foot = rel("foot" + side)
            th_a = _ang(kn)
            out["hip" + side].append(th_a)
            out["kn" + side].append(_ang((foot[0] - kn[0], foot[1] - kn[1])) - th_a)
    for k, vals in out.items():                                    # без скачков через ±180 (как в mocap)
        vals = np.array(vals)
        if k.startswith("wr"):                                      # запястье гнётся не больше чем на ~85°
            vals = np.clip((vals + 180) % 360 - 180, -85, 85)
            for p, v in zip(poses, vals):
                p[k] = round(float(v), 2)
            continue
        for p, v in zip(poses, MC._rel(vals)):
            p[k] = round(float(v), 2)


def hits(P, vis, fps=25):
    """Моменты ударов (секунды), как для записей CMU: кисть дальше всего от таза по горизонтали (пик выше 85-го
    процентиля и заметно дальше обычного) или стопа выше всего относительно таза (пинок) — и только если сразу после
    пика рука (нога) пошла назад: вытянутая и удержанная рука (прицеливание, указывает) — не удар. Почти невидимые руки
    и ноги (дальняя сторона сбоку) не считаются — по ним одни догадки."""
    leg = float(np.median(np.hypot(P["kn1"][0] - P["hip1"][0], P["kn1"][1] - P["hip1"][1])
                          + np.hypot(P["foot1"][0] - P["kn1"][0], P["foot1"][1] - P["kn1"][1]))) or 1.0
    seen = {"hand1": 16, "hand2": 15, "foot1": 28, "foot2": 27}
    out = []
    for limb, j in seen.items():
        if np.median(vis[:, j]) < 0.5:
            continue
        if limb.startswith("hand"):
            d = np.abs(P[limb][0] - P["hip"][0])
            thr, ok = np.percentile(d, 85), max(d.mean() * 1.15, leg * 0.45)
        else:
            d = P["hip"][1] - P[limb][1]                              # y вниз: чем больше, тем выше стопа над тазом
            thr, ok = d.min() + (d.max() - d.min()) * 0.7, -leg * 0.35   # пинок: стопа поднялась хотя бы к поясу
        k = max(2, int(round(fps * 0.45)))                             # удар — выброс и сразу назад: за 0,45 с после
        for i in range(1, len(d) - 1):                                # пика кисть (стопа) вернулась хотя бы на четверть ноги
            back = len(d[i + 1:i + k + 1]) and d[i] - d[i + 1:i + k + 1].min() > leg * 0.25
            if d[i] >= thr and d[i] > ok and back and d[i] >= d[i - 1] and d[i] >= d[i + 1]:
                if all(abs(i / fps - t) > 0.25 for t in out):
                    out.append(round(i / fps, 2))
    return sorted(out)


USER = "moves_user.json"


def user_path():
    from .config import DATA

    return DATA / USER


def save(name, move):
    """Добавить движение в личную библиотеку под именем name (латиница/цифры/подчёркивание)."""
    import re

    tr = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                  ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
                   "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
    latin = "".join(tr.get(ch, ch) for ch in name.strip().lower())       # «Мой удар» → moy_udar
    key = re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]", "_", latin)).strip("_") or "my_move"
    path = user_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"moves": {}}
    data["moves"][key] = move
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    from . import mocap as MC

    MC.reload()
    return key


def learn(video, name, mirror=None, fps=25, strikes=True):
    """Видео → движение в личной библиотеке. Возвращает (имя, секунд, найдено кадров с человеком из скольких)."""
    pts, _size, w3 = landmarks(video, fps, world=True)
    found = int((~np.isnan(pts[:, 23, 0])).sum())
    if found < len(pts) * 0.5:
        raise VideoMocapError("человек виден только на {} кадрах из {} — снимите во весь рост и посветлее".format(found, len(pts)))
    if mirror is None:
        mirror = faces_left(pts)
    move = to_move(smooth(fill_gaps(pts)), fps, mirror, w3)
    if not strikes:                                              # «это не удар» (танец, прицеливание) — без звёздочек и звуков
        move["hits"] = []
    key = save(name, move)
    return key, round(len(move["poses"]) / fps, 1), (found, len(pts))
