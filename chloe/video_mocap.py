"""Своя хореография: видео с телефона → движение стикмена (захват движения по видео).

Человек снимает себя (лучше сбоку, во весь рост, на ровном фоне, 3–15 секунд). MediaPipe Pose (Google, на процессоре)
находит на каждом кадре 33 точки тела; из них берутся наши суставы (таз, шея, голова, плечи, локти, кисти, бёдра,
колени, стопы), и дальше — тот же перенос на стикмена, что для записей CMU (mocap.angles_2d): углы суставов,
высота таза, шаг вперёд. Движение сохраняется в личную библиотеку (~/.chloe/moves_user.json) под своим именем и сразу
доступно в мультфильмах, в том числе с мультяшным фильтром.

Видео не уходит в интернет: всё считается на этом компьютере. Модель позы (~9 МБ) скачивается один раз в ~/.chloe/models.
"""
import json
import pathlib
import subprocess

import numpy as np

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/"
             "pose_landmarker_full.task")
# точки MediaPipe Pose → наши суставы (правая сторона — «1», левая — «2»; mid — середина двух точек)
LM = {"hip": ("mid", 23, 24), "neck": ("mid", 11, 12), "head": ("mid", 7, 8),
      "sh1": 12, "el1": 14, "hand1": 16, "sh2": 11, "el2": 13, "hand2": 15,
      "hip1": 24, "kn1": 26, "foot1": 28, "hip2": 23, "kn2": 25, "foot2": 27}


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


def landmarks(video, fps=25):
    """Точки тела на каждом кадре: массив (кадры × 33 × 3: x, y в пикселях кадра, видимость) и размер кадра."""
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
    except ImportError:
        raise VideoMocapError("не установлен MediaPipe (pip install mediapipe)") from None
    imgs, (w, h) = frames(video, fps)
    opts = vision.PoseLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=str(ensure_model())),
                                        running_mode=vision.RunningMode.VIDEO, num_poses=1)
    out = np.full((len(imgs), 33, 3), np.nan)
    with vision.PoseLandmarker.create_from_options(opts) as det:
        for i, img in enumerate(imgs):
            res = det.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img)),
                                       int(i * 1000 / fps))
            if res.pose_landmarks:
                for j, lm in enumerate(res.pose_landmarks[0]):
                    out[i, j] = (lm.x * w, lm.y * h, getattr(lm, "visibility", 1.0) or 1.0)
    return out, (w, h)


def fill_gaps(pts, min_vis=0.4):
    """Кадры, где человек не нашёлся или точка невидима, — заполнить по соседним (линейно), края — ближайшим."""
    pts = pts.copy()
    n = len(pts)
    for j in range(pts.shape[1]):
        bad = np.isnan(pts[:, j, 0]) | (pts[:, j, 2] < min_vis)
        good = np.where(~bad)[0]
        if len(good) == 0:
            continue
        for c in (0, 1):
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
    return out


def to_move(pts, fps=25, mirror=False):
    """Точки тела (пиксели, y вниз) → движение стикмена: {"poses", "fwd", "fps", "loop", "hits", "lands"}.
    mirror — человек на видео смотрит влево (тогда отражаем, чтобы «вперёд» было вправо)."""
    from . import mocap as MC

    def get(spec):
        if isinstance(spec, tuple):
            return (pts[:, spec[1], :2] + pts[:, spec[2], :2]) / 2
        return pts[:, spec, :2]

    sign = -1.0 if mirror else 1.0
    P = {k: (get(v)[:, 0] * sign, get(v)[:, 1]) for k, v in LM.items()}
    r = MC.angles_2d(P, fps)
    r.update(loop=False, hits=[], lands=[], src="video")
    hand = [np.hypot(P["hand1"][0] - P["hip"][0], 0)]                       # удары: кисть дальше всего от корпуса
    d = np.abs(P["hand1"][0] - P["hip"][0])
    leg = float(np.median(np.hypot(P["kn1"][0] - P["hip1"][0], P["kn1"][1] - P["hip1"][1])) * 2) or 1.0
    for i in range(1, len(d) - 1):
        if d[i] > leg * 0.9 and d[i] >= d[i - 1] and d[i] >= d[i + 1] and all(abs(i / fps - h) > 0.3 for h in r["hits"]):
            r["hits"].append(round(i / fps, 2))
    del hand
    return r


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


def learn(video, name, mirror=False, fps=25):
    """Видео → движение в личной библиотеке. Возвращает (имя, секунд, найдено кадров с человеком из скольких)."""
    pts, _size = landmarks(video, fps)
    found = int((~np.isnan(pts[:, 23, 0])).sum())
    if found < len(pts) * 0.5:
        raise VideoMocapError("человек виден только на {} кадрах из {} — снимите во весь рост и посветлее".format(found, len(pts)))
    move = to_move(smooth(fill_gaps(pts)), fps, mirror)
    key = save(name, move)
    return key, round(len(move["poses"]) / fps, 1), (found, len(pts))
