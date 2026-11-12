"""3D-человек из Blender: движение, выученное с видео (chloe/video_mocap.py, 3D-скелет MediaPipe), повторяет
реалистичный человек без лица в одежде — с физикой ткани, автоматом или пистолетом в руках, с любой стороны.

Нужны (ставятся один раз, без прав администратора):
  • Blender 5.2 LTS — архив с blender.org в ~/.local/share/blender (или blender в PATH, или CHLOE_BLENDER=путь);
  • MPFB — дополнение MakeHuman для Blender (GPL), и ассеты MakeHuman (CC0: тело, одежда, обувь).
Сценарий для Blender — chloe/data/blender/human3d.py; Blender запускается отдельным процессом без окна.

Скорость: на встроенной видеокарте Intel ~4–5 с на кадр 960×540 (10 секунд движения — около 20 минут);
с работающей видеокартой NVIDIA — в разы быстрее.
"""
import glob
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time

SCRIPT = pathlib.Path(__file__).parent / "data" / "blender" / "human3d.py"
VIEWS = ("34", "filmed", "side", "front")
PROPS = ("rifle", "pistol")
OUTFITS = ("male_casualsuit01", "male_casualsuit02", "male_casualsuit03", "male_casualsuit04", "male_casualsuit05",
           "male_casualsuit06", "male_worksuit01", "male_elegantsuit01")
SECONDS_PER_FRAME = 4.5                 # встроенная Intel UHD 630, 960×540, EEVEE (для оценки времени)


class Human3DError(Exception):
    pass


def blender_path():
    """Где Blender: CHLOE_BLENDER → ~/.local/share/blender/blender-*/blender (новейший) → blender в PATH."""
    env = os.environ.get("CHLOE_BLENDER")
    if env and os.path.isfile(env):
        return env
    found = sorted(glob.glob(os.path.expanduser("~/.local/share/blender/blender-*/blender")))
    if found:
        return found[-1]
    return shutil.which("blender")


def mpfb_installed():
    """Стоит ли MPFB (расширение Blender) и ассеты MakeHuman (одежда)."""
    ext = glob.glob(os.path.expanduser("~/.config/blender/*/extensions/user_default/mpfb/__init__.py"))
    clothes = glob.glob(os.path.expanduser("~/.config/blender/*/extensions/.user/user_default/mpfb/data/clothes/*/*.mhclo"))
    return bool(ext) and bool(clothes)


def available():
    return bool(blender_path()) and mpfb_installed()


def why_not():
    if not blender_path():
        return "не найден Blender (архив с blender.org в ~/.local/share/blender)"
    if not mpfb_installed():
        return "в Blender нет MPFB или одежды MakeHuman"
    return ""


def norm_props(props):
    """Предметы по времени: [{"at": 0..1, "prop": "rifle"|"pistol"|None}] — лишнее отбрасывается."""
    out = []
    for p in props or []:
        if not isinstance(p, dict):
            continue
        kind = p.get("prop")
        if kind not in PROPS and kind is not None:
            continue
        try:
            at = min(1.0, max(0.0, float(p.get("at", 0))))
        except (TypeError, ValueError):
            continue
        out.append({"at": at, "prop": kind})
    return sorted(out, key=lambda p: p["at"])


def estimate(frames):
    """Сколько минут займёт рендер (по скорости встроенной видеокарты)."""
    return max(1, round(frames * SECONDS_PER_FRAME / 60))


def command(move_json, out_dir, view="34", size=(960, 540), outfit="male_casualsuit04", shoes="shoes01", props=(),
            cloth=True, frames="all"):
    """Команда запуска Blender без окна (список аргументов)."""
    if view not in VIEWS:
        view = "34"
    if outfit not in OUTFITS:
        outfit = "male_casualsuit04"
    return [blender_path() or "blender", "-b", "-P", str(SCRIPT), "--", "--move", str(move_json), "--out", str(out_dir),
            "--frames", frames, "--view", view, "--size", "{}x{}".format(*size), "--outfit", outfit, "--shoes", shoes,
            "--props", json.dumps(norm_props(props)), "--cloth", "1" if cloth else "0"]


def render(move_name, out, view="34", size=(960, 540), outfit="male_casualsuit04", props=(), cloth=True,
           progress=lambda done, total: None, frames="all", timeout=4 * 3600):
    """Движение move_name (из библиотеки, с 3D-скелетом) → видео mp4 с 3D-человеком. Возвращает путь к видео."""
    from . import mocap as MC
    from . import studio

    if not available():
        raise Human3DError(why_not())
    move = MC.library().get(move_name)
    if not move or not move.get("body3d"):
        raise Human3DError("у движения «{}» нет 3D-скелета — выучите его заново по видео".format(move_name))
    out = pathlib.Path(out)
    with tempfile.TemporaryDirectory(prefix="chloe-3d-") as tmp:
        tmp = pathlib.Path(tmp)
        mj = tmp / "move.json"
        mj.write_text(json.dumps({"body3d": move["body3d"], "face3d": move.get("face3d", -90), "fps": move.get("fps", 25)}),
                      encoding="utf-8")
        frames_dir = tmp / "frames"
        frames_dir.mkdir()
        cmd = command(mj, frames_dir, view, size, outfit, "shoes01", props, cloth, frames)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        t0, tail = time.time(), []
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-20:]
            if line.startswith("КАДР"):
                parts = line.split()
                progress(int(parts[1]), int(parts[2]))
            if time.time() - t0 > timeout:
                proc.kill()
                raise Human3DError("Blender считает слишком долго")
        if proc.wait() != 0 or not any(frames_dir.glob("f*.png")):
            raise Human3DError("Blender не отрендерил: " + " | ".join(t for t in tail if t)[-300:])
        fps = move.get("fps", 25)
        first = min(int(p.stem[1:]) for p in frames_dir.glob("f*.png"))
        out.parent.mkdir(parents=True, exist_ok=True)
        studio.run_ffmpeg(["-framerate", str(fps), "-start_number", str(first), "-i", str(frames_dir / "f%04d.png"),
                           "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                          timeout=600)
    return out
