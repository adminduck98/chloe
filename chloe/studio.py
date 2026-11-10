"""Creative Studio — ролик из идеи: сцены (картинка + закадровый текст) → озвучка → готовый mp4.

Сценарий пишет мозг Chloe (это аргументы инструмента make_film), здесь — производство:
1. для каждой сцены рисуется картинка (Qwen Image) и записывается голос (Светлана, запасной — Qwen);
2. сцена становится клипом: «слайды» — плавный наезд камеры на картинку (дёшево, ~0,25 % пакета за сцену),
   «живое» — картинка оживает (Qwen image-to-video, ~0,9 % пакета за секунду);
3. клипы склеиваются в один файл ffmpeg-ом. Файл — в «Видео/Chloe».
ffmpeg берётся системный или из пакета imageio-ffmpeg (ставится вместе с Chloe, sudo не нужен).
"""
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from . import qwen_media as qm

FPS = 25
FRAMES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}
MAX_SCENES = 8
MIN_SCENE = 3.0          # секунды: короче сцена мелькает
TAIL = 0.5               # пауза после фразы
SLIDE_COST = 0.25        # % месячного Token Plan за сцену (замер 9.11.2026)
LIVE_COST = 0.9          # % за секунду живого видео 720P (замер 10.11.2026)


class StudioError(Exception):
    pass


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise StudioError("нет программы ffmpeg — поставьте: .venv/bin/pip install imageio-ffmpeg "
                          "(или sudo apt install ffmpeg)") from None


def run_ffmpeg(args, timeout=300):
    try:
        r = subprocess.run([ffmpeg(), "-hide_banner", "-y"] + [str(a) for a in args], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise StudioError("ffmpeg не закончил за {} с".format(timeout)) from None
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0:
        raise StudioError("ffmpeg: " + (err.strip().splitlines() or ["ошибка"])[-1][:200])
    return err


def duration(path):
    """Длина звука или видео в секундах (ffmpeg печатает её в «Duration: 00:00:04.32»)."""
    try:
        r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise StudioError("ffmpeg не прочитал файл") from None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr.decode("utf-8", "replace"))
    if not m:
        raise StudioError("не удалось узнать длину {}".format(pathlib.Path(path).name))
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def clean_scenes(scenes):
    """Сцены от мозга → [{picture, narration}]; пустые отбрасываются, лишние обрезаются."""
    out = []
    for s in scenes or []:
        if not isinstance(s, dict):
            continue
        picture = str(s.get("picture") or s.get("image") or "").strip()
        narration = str(s.get("narration") or s.get("text") or "").strip()
        if picture:
            out.append({"picture": picture, "narration": narration})
    return out[:MAX_SCENES]


def estimate(scenes, mode):
    """Примерная цена в процентах месячного пакета Qwen."""
    n = len(scenes)
    if mode != "live":
        return n * SLIDE_COST
    secs = sum(max(MIN_SCENE, min(15, len(s["narration"]) / 14 + TAIL)) for s in scenes)   # ~14 знаков в секунду
    return n * SLIDE_COST + secs * LIVE_COST


def narrate(text, path):
    """Закадровый голос → mp3. Пустой текст — сцена без слов (None)."""
    if not text:
        return None
    from .voice import voice_mp3

    data = voice_mp3(text)
    if not data:
        from . import qwen_audio

        try:
            data = qwen_audio.tts_mp3(text)
        except Exception as e:
            raise StudioError("голос не записался ({})".format(str(e)[:80])) from None
    pathlib.Path(path).write_bytes(data)
    return path


AUDIO_OUT = ["-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]
VIDEO_OUT = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", FPS]


def _audio_in(voice_file, secs):
    """Вход звука для клипа: голос (дополненный тишиной до длины клипа) или тишина."""
    if voice_file:
        return ["-i", voice_file], "[1:a]apad,atrim=0:{:.2f}[a]".format(secs)
    return ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"], "[1:a]atrim=0:{:.2f}[a]".format(secs)


def slide_clip(image, voice_file, secs, size, out, index=0):
    """Картинка → клип: медленный наезд (чётные сцены) или отъезд (нечётные), плавное появление и уход."""
    w, h = size
    frames = int(secs * FPS)
    zoom = "1+0.12*on/{}".format(frames) if index % 2 == 0 else "1.12-0.12*on/{}".format(frames)
    video = ("[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             "zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps},"
             "fade=t=in:st=0:d=0.4,fade=t=out:st={fo:.2f}:d=0.4[v]").format(
        W=w * 2, H=h * 2, z=zoom, d=frames, w=w, h=h, fps=FPS, fo=max(0, secs - 0.4))
    a_in, a_filter = _audio_in(voice_file, secs)
    run_ffmpeg(["-loop", "1", "-i", image] + a_in + ["-filter_complex", video + ";" + a_filter, "-map", "[v]", "-map", "[a]",
               "-t", "{:.2f}".format(secs)] + VIDEO_OUT + AUDIO_OUT + [out])
    return out


def live_clip(video, voice_file, secs, size, out):
    """Живое видео от Qwen → клип нужной длины и размера со своим звуком (последний кадр замирает, если видео короче)."""
    w, h = size
    v = ("[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},"
         "tpad=stop_mode=clone:stop_duration={pad:.2f},trim=0:{s:.2f},setpts=PTS-STARTPTS,"
         "fade=t=in:st=0:d=0.4,fade=t=out:st={fo:.2f}:d=0.4[v]").format(w=w, h=h, fps=FPS, pad=secs, s=secs, fo=max(0, secs - 0.4))
    a_in, a_filter = _audio_in(voice_file, secs)
    run_ffmpeg(["-i", video] + a_in + ["-filter_complex", v + ";" + a_filter, "-map", "[v]", "-map", "[a]",
               "-t", "{:.2f}".format(secs)] + VIDEO_OUT + AUDIO_OUT + [out])
    return out


def join(clips, out):
    """Клипы одного формата → один файл (без перекодирования)."""
    lst = pathlib.Path(out).with_suffix(".txt")
    lst.write_text("".join("file '{}'\n".format(str(c).replace("'", "'\\''")) for c in clips), encoding="utf-8")
    try:
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    finally:
        lst.unlink(missing_ok=True)
    return out


def make_scene(i, scene, style, ratio, mode, size, work, progress=lambda text: None):
    """Одна сцена целиком: картинка, голос, клип. Возвращает путь к клипу."""
    prompt = scene["picture"] + (". " + style if style else "")
    image = qm.image(prompt, ratio)[0]
    voice_file = narrate(scene["narration"], work / "voice{}.mp3".format(i))
    secs = max(MIN_SCENE, (duration(voice_file) + TAIL) if voice_file else MIN_SCENE)
    clip = work / "clip{:02d}.mp4".format(i)
    if mode == "live":
        task = qm.video_start(scene["picture"], str(image), seconds=min(15, int(secs + 0.99)), resolution="720P")
        raw = qm.video_wait(task, "сцена-{}".format(i + 1))
        try:
            live_clip(raw, voice_file, secs, size, clip)
        finally:
            pathlib.Path(raw).unlink(missing_ok=True)       # сырой клип сцены в «Видео/Chloe» не нужен
    else:
        slide_clip(image, voice_file, secs, size, clip, i)
    progress("сцена {} готова".format(i + 1))
    return clip


def make_film(title, scenes, style="", ratio="16:9", mode="slides", progress=lambda text: None, workers=3):
    """Весь ролик. Возвращает путь к mp4 в «Видео/Chloe»."""
    scenes = clean_scenes(scenes)
    if not scenes:
        raise StudioError("нет сцен: нужна хотя бы одна с описанием картинки")
    ratio = ratio if ratio in FRAMES else "16:9"
    size = FRAMES[ratio]
    ffmpeg()                                   # нет ffmpeg — скажем сразу, а не после минут рисования
    with tempfile.TemporaryDirectory(prefix="chloe-film-") as tmp:
        work = pathlib.Path(tmp)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = [pool.submit(make_scene, i, s, style, ratio, mode, size, work, progress) for i, s in enumerate(scenes)]
            try:
                clips = [j.result() for j in jobs]
            except qm.MediaError as e:
                for j in jobs:
                    j.cancel()
                raise StudioError(str(e)) from None
        qm.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        out = qm.VIDEO_DIR / "{}-{}.mp4".format(time.strftime("%Y%m%d-%H%M%S"), qm._slug(title or scenes[0]["picture"]))
        join(clips, out)
    return out
