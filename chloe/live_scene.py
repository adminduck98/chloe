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
HEROINE_REF = Path(__file__).parent / "assets" / "styles" / "live-scene-heroine.png"   # героиня из образца, на белом
ENHANCE = ("Image 1 is the layout made by our code; image 2 is the approved quality and style sample. Redraw image 1 in the "
           "exact rendering quality and art style of image 2: lush detailed voxel foliage, rich grass with tiny flowers, clear "
           "water with stones, beautiful soft light, soft clouds, and the cute detailed voxel girl exactly like in image 2 "
           "(long white hair with light blue tips, big blue eyes, glowing cyan headphones, white hoodie, navy shorts, striped "
           "socks). Keep from image 1: the island shape and camera angle, where the tree, the pond and the girl stand, her "
           "pose, and the season and time of day. Do not copy the layout of image 2. No text, no watermark.")
PLACE_ENHANCE = ("Image 1 is the layout made by our code; image 2 is the approved quality and style sample. Redraw image 1 "
                 "in the exact rendering quality and art style of image 2: lush detailed voxel foliage, rich grass with tiny "
                 "flowers, clear water with stones, beautiful soft light, soft clouds. Keep from image 1: the island shape, "
                 "size and position in the frame, the camera angle, where the tree and the pond are, and the season and time "
                 "of day. Do not copy the layout of image 2. No text, no watermark.")
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


def _blender(env, out_dir):
    exe = shutil.which("blender")
    if not exe:
        raise SceneError("нет Blender — поставьте: sudo apt install blender")
    run = subprocess.run([exe, "-b", "-P", str(ISLAND), "--", str(out_dir)], env=dict(os.environ, **env),
                         capture_output=True, text=True, timeout=7200)
    frames = sorted(Path(out_dir).glob("v*.png"))
    if run.returncode or not frames:
        raise SceneError("Blender не нарисовал остров: " + (run.stderr or run.stdout)[-200:])
    return frames


def sky(season, w, h):
    """Небо кодом: градиент времени года и мягкие облака."""
    import cv2

    top, mid, bot = (np.array(c, np.float32) for c in SKY.get(season, SKY["spring"]))
    yy = np.linspace(0, 1, h)[:, None, None]
    out = np.where(yy < 0.55, top + (mid - top) * (yy / 0.55), mid + (bot - mid) * ((yy - 0.55) / 0.45))
    out = np.repeat(out, w, axis=1)
    rng = np.random.default_rng(2)
    k = w / 928
    for _ in range(6):
        m = np.zeros((h, w), np.float32)
        cx, cy = int(rng.integers(0, w)), int(rng.integers(h // 2, h))
        for _ in range(8):
            cv2.ellipse(m, (cx + int(rng.integers(-150, 150) * k), cy + int(rng.integers(-25, 25) * k)),
                        (int(rng.integers(50, 120) * k), int(rng.integers(25, 50) * k)), 0, 0, 360, 1.0, -1)
        m = cv2.GaussianBlur(m, (0, 0), 18 * k)[..., None] * (0.15 if season == "night" else 0.4)
        out = out * (1 - m) + np.array((255, 236, 236), np.float32) * m
    return out


def _on_sky(frame, back):
    from PIL import Image

    rgba = np.array(Image.open(frame).convert("RGBA")).astype(np.float32)
    al = rgba[..., 3:] / 255
    return np.clip(back * (1 - al) + rgba[..., :3] * al, 0, 255).astype(np.uint8)


def render_island(season, out_png, samples=64):
    """Blender строит и рисует остров кодом (без окна), код подкладывает небо. Возвращает путь к кадру 928×1664."""
    from PIL import Image

    with tempfile.TemporaryDirectory() as d:
        frame = _blender(dict(VOX_FRAMES="1", VOX_W="928", VOX_H="1664", VOX_SEASON=season, VOX_SAMPLES=str(samples)), d)[0]
        Image.fromarray(_on_sky(frame, sky(season, 928, 1664))).save(out_png)
    return Path(out_png)


PLACE_TEXT = ("Image 1 has no character on the island: do not add the girl or any people, animals or characters — "
              "leave the island empty, only the scenery.")


def render_place(season, out_png, samples=64):
    """Место отдельно: Blender рисует остров без героини и говорит, где она стоит и какого роста (доли кадра)."""
    import json
    from PIL import Image

    with tempfile.TemporaryDirectory() as d:
        frame = _blender(dict(VOX_FRAMES="1", VOX_W="928", VOX_H="1664", VOX_SEASON=season, VOX_SAMPLES=str(samples),
                              VOX_NO_HERO="1"), d)[0]
        spot = json.loads((Path(d) / "spot.json").read_text())
        Image.fromarray(_on_sky(frame, sky(season, 928, 1664))).save(out_png)
    return Path(out_png), spot


def top_box(path, season):
    """Верх острова (трава, листва, снег) — рамка в долях кадра; None, если не нашёлся."""
    import cv2
    from PIL import Image

    a = np.array(Image.open(path).convert("RGB").resize((232, 416), Image.BOX))
    hsv = cv2.cvtColor(a, cv2.COLOR_RGB2HSV).astype(np.int32)
    hh, ss, vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    tex = cv2.GaussianBlur(np.abs(cv2.Laplacian(a.astype(np.float32).mean(-1), cv2.CV_32F, ksize=3)), (0, 0), 2)
    if season == "winter":                                             # снег белый, как небо, — но пёстрый, а небо гладкое
        m = (ss < 50) & (vv > 180) & (tex > 6)
    elif season == "autumn":
        m = (hh >= 15) & (hh <= 45) & (ss > 60) & (vv > 90)
    elif season == "night":
        m = (hh >= 30) & (hh <= 95) & (vv > 40) & (tex > 6)
    else:
        m = (hh >= 30) & (hh <= 95) & (ss > 45) & (vv > 70)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = st[i, :4]
    if w < 232 * 0.3 or st[i, cv2.CC_STAT_AREA] < 232 * 416 * 0.03:
        return None
    return np.array([x, y, x + w, y + h], np.float64) / [232, 416, 232, 416]


def island_map(before, after, season):
    """Как Qwen сдвинул и масштабировал остров: (k, dx, dy) в долях кадра, x' = k·x + dx, y' = k·y + dy
    (по переднему краю и ширине верха острова). Не нашёл — без сдвига."""
    a, b = top_box(before, season), top_box(after, season)
    if a is None or b is None:
        return 1.0, 0.0, 0.0
    k = (b[2] - b[0]) / (a[2] - a[0])
    return float(k), float(b[0] - a[0] * k), float(b[3] - a[3] * k)


def follow_spot(spot, before, after, season):
    """Точка героини на картинке, которую Qwen перерисовал (17.11.2026: героиня повисла в воздухе)."""
    k, dx, dy = island_map(before, after, season)
    if (k, dx, dy) == (1.0, 0.0, 0.0):
        return spot
    return {"x": k * spot["x"] + dx, "y": k * spot["y"] + dy, "top": k * spot["top"] + dy}


def render_heroine(moves, season, out_dir=None, samples=32):
    """3D-героиня (chloe/blender/hero3d.py) в сцене острова: тот же свет и камера; рисуется только она и её тень
    на острове, фон прозрачный. Кадры 15 в секунду, 464×832. Готовые кадры хранятся в «Видео/Chloe/work»:
    героиня не зависит от картинки места, и повторная сборка не ждёт Blender."""
    work = Path(out_dir) if out_dir else qm.VIDEO_DIR / "work" / "geroinya-{}-{}".format("-".join(moves), season)
    frames = sorted(work.glob("v*.png")) if work.exists() else []
    from . import heroine3d as H3

    need = int(round(H3.plan(moves)[1] * 15))
    if len(frames) >= need:
        return frames[:need]
    work.mkdir(parents=True, exist_ok=True)
    return _blender(dict(VOX_HERO3D="1", VOX_HERO3D_MOVES=",".join(moves), VOX_W="464", VOX_H="832",
                         VOX_SEASON=season, VOX_SAMPLES=str(samples)), work)


def clean_heroine(rgba):
    """Кадр героини: убрать шум рендера (NLM, края целы) и оставить тень только у ног — тени, пойманные
    островом кода в других местах, на картинке Qwen легли бы не туда (17.11.2026: серая полоса в небе)."""
    import cv2

    a = rgba[..., 3]
    body = a > 240
    if body.any():
        ys, xs = np.nonzero(body)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        w, h = x1 - x0, y1 - y0
        keep = np.zeros_like(body)
        cy, cx = y1, (x0 + x1) // 2
        cv2.ellipse(keep.view(np.uint8), (int(cx), int(cy)), (int(w * 0.9 + 6), int(h * 0.18 + 6)), 0, 0, 360, 1, -1)
        keep |= body
        a = np.where(keep, a, 0).astype(np.uint8)
        a = cv2.GaussianBlur(a.astype(np.float32), (0, 0), 0.6).clip(0, 255).astype(np.uint8) * (~body) + a * body
    den = cv2.fastNlMeansDenoisingColored(np.ascontiguousarray(rgba[..., :3]), None, 4, 4, 5, 11)
    rgb = ((den.astype(np.float32) + rgba[..., :3].astype(np.float32)) / 2).astype(np.uint8)   # пополам: зерно меньше,
                                                                                               # бледные детали худи целы
    return np.dstack([rgb, a.astype(np.uint8)])


def heroine_overlay(frames, mapping):
    """Кадры героини → функция для animate: кладёт нужный кадр на картинку места с учётом сдвига от Qwen."""
    import cv2
    from PIL import Image

    k, dx, dy = mapping
    cache = {}

    def draw(t, base, s):
        i = min(len(frames) - 1, int(t * 15))
        if i not in cache:
            cache.clear()
            cache[i] = clean_heroine(np.array(Image.open(frames[i]).convert("RGBA"))).astype(np.float32)
        h = cache[i]
        bh, bw = base.shape[:2]
        M = np.float32([[k * bw / h.shape[1], 0, dx * bw], [0, k * bh / h.shape[0], dy * bh]])
        w = cv2.warpAffine(h, M, (bw, bh), flags=cv2.INTER_LINEAR)
        a = w[..., 3:] / 255
        base[:] = base * (1 - a) + w[..., :3] * a
    return draw


def make_with_heroine(moves=None, idea="", better=True):
    """Персонаж и место отдельно: Blender строит место без героини → Qwen доводит место до образца → Blender рисует
    3D-героиню (TRELLIS по рисунку-образцу) с движениями кодом в том же свете → код кладёт её на место туда, куда Qwen
    сдвинул остров → ролик 1080×1920. Возвращает [ролик, место]."""
    from . import heroine3d as H3

    kind = particles_for(idea)
    season = SEASON_OF.get(kind, "spring")
    steps, total = H3.plan(moves)
    names = [m for m, _, _ in steps]
    qm.IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    qm.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    stamp = __import__("time").strftime("%Y%m%d-%H%M%S")
    place, _ = render_place(season, qm.IMAGE_DIR / "{}-mesto-{}.png".format(stamp, season))
    pic, ok = enhance(place, season, PLACE_TEXT) if better else (place, False)
    mapping = island_map(place, pic, season) if ok else (1.0, 0.0, 0.0)
    out = qm.VIDEO_DIR / "{}-geroinya-{}.mp4".format(stamp, "-".join(names))
    frames = render_heroine(names, season)
    animate(pic, out, total, kind, overlay=heroine_overlay(frames, mapping))
    return [out, pic]


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


def enhance(path, season="spring", extra="", tries=2):
    """Qwen перерисовывает кадр кода в качестве утверждённого образца, сохраняя раскладку, позу и время года.
    Подменил время года — ещё раз, потом остаётся кадр кода. Возвращает (кадр, улучшен ли)."""
    text = ENHANCE + " " + SEASON_TEXT.get(season, "")
    if extra:                                                          # место без героини — свой запрос
        text = PLACE_ENHANCE + " " + SEASON_TEXT.get(season, "") + " " + extra
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


def animate(src, out, seconds=6.0, particles="petals", seed=9, overlay=None):
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
            scene_img = base
            if overlay:                                                # героиня — на место, до камеры: двигаются вместе
                scene_img = base.copy()
                overlay(f / FPS, scene_img, k0)
            fr = cv2.warpAffine(scene_img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
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
