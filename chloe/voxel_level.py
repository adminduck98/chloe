"""Воксельный 3D-уровень «внутри игры» → готовый ролик Shorts 1080×1920.

1. Blender строит и рендерит сцену (chloe/blender/voxel_level.py): земля из кубиков, тропинка, шипы, яма, блок «?»,
   монеты, портал, деревня с сакурой, холмы; героиня Мия бежит и прыгает по плану уровня.
2. Здесь — поверх кадров: счёт, монеты, жизни, вспышка при ударе по блоку, «Уровень пройден!» в конце.
   Всё по тому же плану (chloe/level_plan.py), поэтому счёт совпадает с тем, что видно в кадре.
3. ffmpeg склеивает mp4.

Blender — системный (`blender`, sudo apt install blender) или Blender-модуль для Python: CHLOE_BPY_PYTHON —
путь к python, в котором стоит `pip install bpy` (так работает и без установленного Blender).
Запуск: python -m chloe.voxel_level ролик.mp4  (LV_SAMPLES, LV_W, LV_H, LV_FPS — качество и размер).
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

from . import level_plan as LP

SCENE = pathlib.Path(__file__).parent / "blender" / "voxel_level.py"
OUT_W, OUT_H = 1080, 1920
FONTS = ("/usr/share/fonts/truetype/noto/NotoSans-Black.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


class LevelError(Exception):
    pass


def blender_cmd():
    """Как запустить сцену: системный Blender или python с модулем bpy."""
    py = os.environ.get("CHLOE_BPY_PYTHON")
    if py and os.path.exists(py):
        return [py, str(SCENE), "--"]
    exe = shutil.which("blender")
    if exe:
        return [exe, "-b", "--python-exit-code", "1", "-P", str(SCENE), "--"]
    raise LevelError("нет Blender — поставьте: sudo apt install blender (или pip install bpy и CHLOE_BPY_PYTHON)")


def render_frames(out_dir, w=540, h=960, fps=15, samples=12, only=None, progress=print):
    env = dict(os.environ, LV_W=str(w), LV_H=str(h), LV_FPS=str(fps), LV_SAMPLES=str(samples))
    if only:
        env["LV_ONLY"] = ",".join(str(f) for f in only)
    cmd = blender_cmd() + [str(out_dir)]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0 or "LEVEL_FRAMES" not in proc.stdout:
        raise LevelError("сцена не отрендерилась: " + (proc.stderr or proc.stdout)[-400:])
    return sorted(pathlib.Path(out_dir).glob("f_*.png"))


def _font(size):
    from PIL import ImageFont

    for f in FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def _outlined(d, xy, text, font, fill, stroke=(40, 22, 60), sw=6, anchor="la"):
    d.text(xy, text, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)


def overlay(img, ev, f, fps, plan, lives=3):
    """HUD поверх кадра 1080×1920: монеты, очки, жизни; вспышка при ударе; финальная надпись."""
    from PIL import Image, ImageDraw

    img = img.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    W, _ = img.size
    top = 70
    d.rounded_rectangle((40, top, W - 40, top + 110), radius=55, fill=(30, 20, 60, 110))
    # монета
    cx, cy, r = 110, top + 55, 30
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 201, 61, 255), outline=(150, 80, 20, 255), width=5)
    d.ellipse((cx - r * 0.45, cy - r * 0.6, cx + r * 0.05, cy + r * 0.2), fill=(255, 240, 170, 255))
    _outlined(d, (160, cy), "× {}".format(ev["coins"]), _font(56), (255, 255, 255, 255), anchor="lm")
    _outlined(d, (W // 2 + 40, cy), "{:06d}".format(ev["score"]), _font(56), (255, 236, 150, 255), anchor="mm")
    for i in range(3):                                                         # сердечки
        x = W - 110 - i * 78
        col = (255, 79, 109, 255) if i < lives else (70, 50, 90, 200)
        d.ellipse((x - 30, cy - 24, x + 2, cy + 8), fill=col)
        d.ellipse((x - 2, cy - 24, x + 30, cy + 8), fill=col)
        d.polygon([(x - 29, cy - 4), (x + 29, cy - 4), (x, cy + 30)], fill=col)
    out = Image.alpha_composite(img, layer)
    # всплывающее «+100» и вспышка при ударе по блоку
    hit = ev["block_hit"]
    if hit is not None and 0 <= (f - hit) / fps < 0.8:
        k = (f - hit) / fps / 0.8
        pop = Image.new("RGBA", img.size, (0, 0, 0, 0))
        pd = ImageDraw.Draw(pop)
        a = int(255 * (1 - k))
        _outlined(pd, (W // 2 - 120, int(820 - 160 * k)), "+100", _font(90), (255, 214, 0, a), stroke=(90, 40, 0, a), sw=8, anchor="mm")
        out = Image.alpha_composite(out, pop)
    t = f / fps
    if t > plan.portal_t + 0.5:                                                 # финал
        k = LP.ease((t - plan.portal_t - 0.5) / 0.35)
        fin = Image.new("RGBA", img.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fin)
        size = int(120 * (0.6 + 0.4 * k))
        a = int(255 * k)
        y = int(560 - 60 * (1 - k))
        _outlined(fd, (W // 2, y), "УРОВЕНЬ", _font(size), (255, 225, 90, a), stroke=(110, 40, 90, a), sw=12, anchor="mm")
        _outlined(fd, (W // 2, y + size + 20), "ПРОЙДЕН!", _font(size), (255, 225, 90, a), stroke=(110, 40, 90, a), sw=12, anchor="mm")
        out = Image.alpha_composite(out, fin)
    return out.convert("RGB")


def assemble(frames, out, fps=15, plan=None, crf=18):
    """Кадры Blender → HUD → mp4 1080×1920."""
    from PIL import Image

    from .studio import ffmpeg

    plan = plan or LP.Plan()
    events = plan.events(fps, len(frames) / fps + 1)
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "{}x{}".format(OUT_W, OUT_H),
           "-r", str(fps), "-i", "-", "-vf", "fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
           "-pix_fmt", "yuv420p", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for p in frames:
        f = int(p.stem.split("_")[1])
        img = Image.open(p).convert("RGB").resize((OUT_W, OUT_H), Image.LANCZOS)
        proc.stdin.write(overlay(img, events[min(f, len(events) - 1)], f, fps, plan).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise LevelError("ffmpeg не собрал ролик")
    return out


def make(out, w=540, h=960, fps=15, samples=12, progress=print):
    with tempfile.TemporaryDirectory(prefix="chloe-level-") as tmp:
        progress("Строю и рендерю уровень в Blender…")
        frames = render_frames(tmp, w, h, fps, samples, progress=progress)
        progress("Кадров: {}. Собираю ролик…".format(len(frames)))
        return assemble(frames, out, fps)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "voxel-level.mp4"
    print(make(target, int(os.environ.get("LV_W", 540)), int(os.environ.get("LV_H", 960)),
               int(os.environ.get("LV_FPS", 15)), int(os.environ.get("LV_SAMPLES", 12))))
