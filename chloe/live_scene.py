"""Живая сцена (стиль канала, assets/styles/live-scene.md): всё создаёт код — Blender строит воксельный остров с
героиней (chloe/blender/voxel_island.py), код рисует небо; Qwen только улучшает качество готового кадра, ничего не
меняя; код оживляет его в петлю 1080×1920 — дыхание камеры, частицы в три слоя глубины, мягкий тёплый свет."""
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import qwen_media as qm

W, H, FPS = 1080, 1920, 30
ISLAND = Path(__file__).parent / "blender" / "voxel_island.py"
SAMPLE = Path(__file__).parent / "assets" / "styles" / "live-scene-sample.jpg"   # утверждённый образец качества
ENHANCE = ("Image 1 is the layout made by our code; image 2 is the approved quality and style sample. Redraw image 1 in the "
           "exact rendering quality and art style of image 2: lush detailed voxel foliage, rich grass with tiny flowers, clear "
           "water with stones, beautiful soft light, soft clouds, and the cute detailed voxel girl exactly like in image 2 "
           "(long white hair with light blue tips, big blue eyes, glowing cyan headphones, white hoodie, navy shorts, striped "
           "socks). Keep from image 1: the island shape and camera angle, where the tree, the pond and the girl stand, her "
           "pose, and the season and time of day. Do not copy the layout of image 2. No text, no watermark.")
SEASON_OF = {"snow": "winter", "leaves": "autumn", "stars": "night"}
SEASON_TEXT = {  # Qwen любит «улучшать» зиму в весну (17.11.2026) — время года называем прямо
    "winter": "It is a WINTER scene: the ground, the grass and the tree crown are covered with white snow. Keep all the snow "
              "and the white colors; do not turn it into spring or summer.",
    "autumn": "It is an AUTUMN scene: orange and red foliage and yellowish grass. Keep these autumn colors.",
    "night": "It is NIGHT: a dark blue sky and cool moonlight. Keep it dark; do not turn it into day.",
    "spring": "Spring: pink cherry blossoms. Keep the blossoms pink.",
}
SKY = {  # верх, середина, низ
    "spring": ((48, 64, 136), (214, 140, 172), (255, 208, 172)),
    "autumn": ((60, 58, 120), (226, 132, 104), (255, 204, 140)),
    "winter": ((70, 96, 160), (170, 190, 230), (236, 242, 255)),
    "night": ((8, 10, 32), (28, 34, 86), (70, 64, 130)),
}
PARTICLES = {  # тип: (цвета, размер, вытянутость, скорость падения, ветер)
    "petals": ([(255, 170, 200), (255, 196, 216), (250, 140, 180)], 1.0, 0.55, 1.0, -120),
    "snow": ([(255, 255, 255), (235, 242, 255)], 0.8, 1.0, 0.7, -40),
    "leaves": ([(240, 150, 60), (220, 90, 50), (250, 200, 80)], 1.1, 0.5, 0.9, -160),
    "stars": ([(255, 250, 220), (200, 230, 255)], 0.6, 1.0, -0.25, 0),
    "rain": ([(190, 215, 255)], 0.7, 0.18, 2.6, -60),
    "none": ([], 0, 0, 0, 0),
}
PARTICLE_WORDS = [("snow", r"снег|зим|snow|winter"), ("leaves", r"осен|листопад|autumn|fall"), ("rain", r"дожд|rain"),
                  ("stars", r"ноч|звёзд|звезд|космос|night|star"), ("petals", r"сакур|весн|цвет|лепест|blossom|spring")]


class SceneError(Exception):
    pass


def particles_for(idea, wanted=None):
    if wanted in PARTICLES:
        return wanted
    for kind, rx in PARTICLE_WORDS:
        if re.search(rx, idea or "", re.I):
            return kind
    return "petals"


def render_island(season, out_png, samples=64):
    """Blender строит и рисует остров кодом (без окна), код подкладывает небо. Возвращает путь к кадру 928×1664."""
    import cv2
    from PIL import Image

    exe = shutil.which("blender")
    if not exe:
        raise SceneError("нет Blender — поставьте: sudo apt install blender")
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, VOX_FRAMES="1", VOX_W="928", VOX_H="1664", VOX_SEASON=season, VOX_SAMPLES=str(samples))
        run = subprocess.run([exe, "-b", "-P", str(ISLAND), "--", d], env=env, capture_output=True, text=True, timeout=1800)
        frame = Path(d) / "v000.png"
        if run.returncode or not frame.exists():
            raise SceneError("Blender не нарисовал остров: " + (run.stderr or run.stdout)[-200:])
        rgba = np.array(Image.open(frame).convert("RGBA")).astype(np.float32)
    h, w = rgba.shape[:2]
    top, mid, bot = (np.array(c, np.float32) for c in SKY.get(season, SKY["spring"]))
    yy = np.linspace(0, 1, h)[:, None, None]
    sky = np.where(yy < 0.55, top + (mid - top) * (yy / 0.55), mid + (bot - mid) * ((yy - 0.55) / 0.45))
    sky = np.repeat(sky, w, axis=1)
    rng = np.random.default_rng(2)
    for _ in range(6):                                                 # мягкие облака
        m = np.zeros((h, w), np.float32)
        cx, cy = int(rng.integers(0, w)), int(rng.integers(h // 2, h))
        for _ in range(8):
            cv2.ellipse(m, (cx + int(rng.integers(-150, 150)), cy + int(rng.integers(-25, 25))),
                        (int(rng.integers(50, 120)), int(rng.integers(25, 50))), 0, 0, 360, 1.0, -1)
        m = cv2.GaussianBlur(m, (0, 0), 18)[..., None] * (0.15 if season == "night" else 0.4)
        sky = sky * (1 - m) + np.array((255, 236, 236), np.float32) * m
    al = rgba[..., 3:] / 255
    out = sky * (1 - al) + rgba[..., :3] * al
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(out_png)
    return Path(out_png)


def _share(path, kind):
    """Доля пикселей «примет» времени года: снег, розовый цвет, оранжевая листва — и средняя яркость для ночи."""
    from PIL import Image

    a = np.array(Image.open(path).convert("RGB").resize((64, 112), Image.BOX)).astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    if kind == "winter":
        return float(((a.min(-1) > 215) & (a.max(-1) - a.min(-1) < 25)).mean())
    if kind == "spring":
        return float(((r > 200) & (b > 140) & (r - g > 40)).mean())
    if kind == "autumn":
        return float(((r > 180) & (g > 70) & (g < 175) & (b < 110) & (r - b > 90)).mean())
    return float((r * 0.3 + g * 0.59 + b * 0.11).mean())


def season_kept(src, out, season):
    """Qwen не подменил время года: снег, цветение, листва остались; ночь осталась тёмной (17.11.2026: зима → весна)."""
    a, b = _share(src, season), _share(out, season)
    if season == "night":
        return b <= a + 25
    return a < 0.01 or b >= a * (0.6 if season == "winter" else 0.4)


def enhance(path, season="spring", tries=2):
    """Qwen перерисовывает кадр кода в качестве утверждённого образца, сохраняя раскладку, позу и время года.
    Подменил время года — ещё раз, потом остаётся кадр кода. Возвращает (кадр, улучшен ли)."""
    text = ENHANCE + " " + SEASON_TEXT.get(season, "")
    refs = (str(SAMPLE),) if SAMPLE.exists() else ()
    for _ in range(tries):
        better = qm.image(text, "9:16", 1, source=str(path), refs=refs)[0]
        ok = season_kept(path, better, season)
        print("[живая сцена: время года {}]".format("сохранено" if ok else "подменено — ещё раз"))
        if ok:
            return Path(better), True
    return Path(path), False


def _sprite(cv2, size, blur, stretch):
    s = int(size * 2.6) + 8
    m = np.zeros((s, s), np.float32)
    cv2.ellipse(m, (s // 2, s // 2), (max(1, int(size)), max(1, int(size * stretch))), 0, 0, 360, 1.0, -1)
    if blur:
        m = cv2.GaussianBlur(m, (0, 0), blur)
    return m


def animate(src, out, seconds=6.0, particles="petals", seed=9):
    """Картинка → петля: камера дышит, частицы в три слоя, свет дышит. Возвращает путь к ролику."""
    import cv2
    from PIL import Image

    img = np.array(Image.open(src).convert("RGB")).astype(np.float32)
    sh, sw = img.shape[:2]
    k0 = max(W / sw, H / sh) * 1.08                                    # запас под приближение камеры
    base = cv2.resize(img, (int(sw * k0) + 1, int(sh * k0) + 1), interpolation=cv2.INTER_LANCZOS4)
    bh, bw = base.shape[:2]
    cols, size, stretch, fall, wind = PARTICLES.get(particles, PARTICLES["petals"])
    rng = np.random.default_rng(seed)
    layer = []
    if cols:
        for count, sz, blur, speed, alpha in ((40, 7, 0, 0.6, 0.9), (22, 13, 1.2, 0.9, 0.95), (7, 34, 7, 1.4, 0.75)):
            for _ in range(count):
                layer.append(dict(x=rng.uniform(0, W), ph=rng.random(), sp=speed * rng.uniform(0.8, 1.2),
                                  sw=rng.uniform(30, 90), spr=_sprite(cv2, sz * size * rng.uniform(0.8, 1.2), blur, stretch),
                                  a=alpha, col=np.array(cols[int(rng.integers(len(cols)))], np.float32), rot=rng.uniform(0, 6.28)))
    yy, xx = np.mgrid[0:H:8, 0:W:8]
    light = np.clip(1 - np.hypot((xx - W * 0.85) / (W * 0.9), (yy - H * 0.1) / (H * 0.6)), 0, 1) ** 2
    light = cv2.resize(light.astype(np.float32), (W, H))[..., None]
    warm = np.array((255, 220, 180), np.float32)
    out = str(out)
    from .studio import ffmpeg

    ff = subprocess.Popen([ffmpeg(), "-v", "error", "-y", "-f", "rawvideo",
                           "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                           "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    total = int(FPS * seconds)
    last = b""
    try:
        for f in range(total):
            if f % 2:                                                  # «на двойках»: рисунок меняется 15 раз в секунду
                ff.stdin.write(last)
                continue
            u = f / total
            z = 1.0 + 0.035 * (1 - math.cos(2 * math.pi * u)) / 2
            cw, ch = W / z * (bw / (W * 1.08)), H / z * (bh / (H * 1.08))
            cx, cy = bw / 2, bh / 2 + 14 * math.sin(2 * math.pi * u)
            M = np.float32([[W / cw, 0, W / 2 - cx * W / cw], [0, H / ch, H / 2 - cy * H / ch]])
            fr = cv2.warpAffine(base, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            g = light * (0.5 + 0.5 * math.sin(2 * math.pi * u * 2)) * 0.10
            fr = fr * (1 - g) + warm * g
            for p in layer:
                k = (u * p["sp"] * 2 + p["ph"]) % 1.0
                y = -60 + (H + 120) * (k if fall >= 0 else 1 - k)
                x = (p["x"] + p["sw"] * math.sin(2 * math.pi * (k * 2 + p["ph"])) + wind * k) % (W + 80) - 40
                _stamp(cv2, fr, p["spr"], x, y, p["col"], p["a"], p["rot"] + 6.28 * k * 2)
            last = np.clip(fr, 0, 255).astype(np.uint8).tobytes()
            ff.stdin.write(last)
    finally:
        ff.stdin.close()
        ff.wait()
    if ff.returncode:
        raise SceneError("ffmpeg не собрал ролик")
    return Path(out)


def _stamp(cv2, fr, spr, cx, cy, col, a, angle):
    s = spr.shape[0]
    m = cv2.warpAffine(spr, cv2.getRotationMatrix2D((s / 2, s / 2), math.degrees(angle), 1.0), (s, s)) * a
    x0, y0 = int(cx - s / 2), int(cy - s / 2)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + s), min(H, y0 + s)
    if xa < xb and ya < yb:
        mm = m[ya - y0:yb - y0, xa - x0:xb - x0, None]
        fr[ya:yb, xa:xb] = fr[ya:yb, xa:xb] * (1 - mm) + col * mm


def make(idea="", particles=None, seconds=6.0, source=None, better=True):
    """Код строит сцену (или берётся готовая картинка source) → Qwen улучшает качество → живая петля.
    Возвращает [ролик, кадр]."""
    kind = particles_for(idea, particles)
    season = SEASON_OF.get(kind, "spring")
    qm.IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    qm.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    stamp = __import__("time").strftime("%Y%m%d-%H%M%S")
    frame = Path(source) if source else render_island(season, qm.IMAGE_DIR / "{}-ostrov-{}.png".format(stamp, season))
    pic, _ = enhance(frame, season) if better else (frame, False)
    out = qm.VIDEO_DIR / "{}-zhivaya-scena-{}.mp4".format(stamp, season)
    return [animate(pic, out, seconds, kind), pic]
