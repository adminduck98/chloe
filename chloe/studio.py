"""Creative Studio — ролик из идеи: сцены (картинка + закадровый текст) → озвучка → готовый mp4.

Сценарий пишет мозг Chloe (это аргументы инструмента make_film), здесь — производство:
1. для каждой сцены рисуется картинка (Qwen Image) и записывается голос (Светлана, запасной — Qwen);
2. сцена становится клипом: «слайды» — плавный наезд камеры на картинку (дёшево, ~0,25 % пакета за сцену),
   «живое» — картинка оживает (Qwen image-to-video, ~0,9 % пакета за секунду);
3. клипы склеиваются в один файл ffmpeg-ом. Файл — в «Видео/Chloe».
ffmpeg берётся системный или из пакета imageio-ffmpeg (ставится вместе с Chloe, sudo не нужен).
"""
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from . import qwen_media as qm

log = logging.getLogger("chloe.studio")

FPS = 25
FRAMES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}
MAX_SCENES = 30         # до ~4 минут при 8 с на сцену; цену всё равно называет вопрос перед оплатой
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
            sc = {"picture": picture, "narration": narration}
            for k in ("video", "stage", "place", "beat", "shot"):   # раскадровка: движение, этап сюжета, место, тип сцены, план
                if s.get(k):
                    sc[k] = str(s[k]).strip()
            if isinstance(s.get("anim"), dict):               # мультфильм: кто что делает и когда (chloe/animator.py)
                sc["anim"] = s["anim"]
            if isinstance(s.get("beats"), list):
                sc["beats"] = [str(b).strip() for b in s["beats"] if str(b).strip()][:4]
            out.append(sc)
    return out[:MAX_SCENES]


BG_LOOKS = ("cozy", "prehistoric", "historical")   # цветные миры: фон места рисует нейросеть (одна картинка на место)


def estimate(scenes, mode, look=None):
    """Примерная цена в процентах месячного пакета Qwen. Мультфильм — бесплатно, кроме фонов мест у цветных стилей."""
    n = len(scenes)
    if mode == "anim":
        return len({sc.get("place") for sc in scenes if sc.get("place")}) * SLIDE_COST if look in BG_LOOKS else 0.0
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


def _edge_words(text, path):
    """Голос Светланы + время каждого слова (edge-tts присылает его сам). [(начало, конец, слово)] в секундах или None."""
    import asyncio

    import edge_tts

    from . import persona
    from .config import VOICES

    async def go():
        audio, words = bytearray(), []
        comm = edge_tts.Communicate(text, VOICES[0], boundary="WordBoundary", **persona.edge_args(text))
        async for ch in comm.stream():
            if ch["type"] == "audio":
                audio += ch["data"]
            elif ch["type"] == "WordBoundary":
                st = ch["offset"] / 1e7
                words.append((round(st, 3), round(st + ch["duration"] / 1e7, 3), ch["text"]))
        return bytes(audio), words

    for _ in range(4):                      # сервер иногда отвечает без звука — следующий запрос обычно проходит
        try:
            audio, words = asyncio.run(asyncio.wait_for(go(), 60))
        except Exception:
            continue
        if audio:
            pathlib.Path(path).write_bytes(audio)
            return with_punctuation(words, text)
    return None


def _bare(w):
    return re.sub(r"[^\w]+", "", w.lower().replace("ё", "е"))


def with_punctuation(words, text):
    """Сервер присылает слова без знаков препинания — возвращаем их из текста: субтитры читаются, фразы рвутся по смыслу."""
    tokens, j, out = text.split(), 0, []
    for a, b, w in words:
        k = j
        while k < len(tokens) and _bare(tokens[k]) != _bare(w):
            k += 1
        if k < len(tokens) and k - j <= 3:
            out.append((a, b, tokens[k]))
            j = k + 1
        else:
            out.append((a, b, w))
    return out


def even_words(text, secs):
    """Нет точного времени слов (запасной голос) — по длине слов: приблизительно, не настоящая синхронизация."""
    ws = text.split()
    total = sum(len(w) + 1 for w in ws) or 1
    out, t = [], 0.0
    for w in ws:
        d = secs * (len(w) + 1) / total
        out.append((round(t, 3), round(t + d, 3), w))
        t += d
    return out


def narrate_words(text, path):
    """Закадровый голос + время слов для субтитров: (файл или None, [(начало, конец, слово)], точно ли)."""
    if not text:
        return None, [], True
    from .config import TTS

    if TTS != "qwen":
        words = _edge_words(text, path)
        if words is not None:
            return path, words, bool(words)
    narrate(text, path)
    return path, even_words(text, max(0.5, duration(path) - 0.2)), False


def phrases(words, max_words=5, max_chars=32):
    """Слова → короткие фразы субтитров: [(начало, конец, текст)]. Рвём по знакам препинания и по длине."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x[2] for x in cur)
        if len(cur) >= max_words or len(text) >= max_chars or re.search(r"[.!?…,;:—]$", w[2]):
            out.append((cur[0][0], cur[-1][1], text))
            cur = []
    if cur:
        out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
    # фраза держится до следующей (без мигания пустотой), но не дольше 1,2 с после последнего слова
    fixed = []
    for i, (a, b, t) in enumerate(out):
        nxt = out[i + 1][0] if i + 1 < len(out) else b + 1.2
        fixed.append((a, max(a + 0.3, min(b + 1.2, max(b, nxt))), t))
    return fixed


def _ass_time(t):
    t = max(0.0, t)
    return "{}:{:02d}:{:05.2f}".format(int(t // 3600), int(t % 3600 // 60), t % 60)


def captions_ass(words, size, path, shift=0.0):
    """Файл субтитров ASS: короткие фразы внизу кадра, белый текст с тёмной обводкой — читается на любом фоне."""
    w, h = size
    fs = round(min(w, h) * 0.058)
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Cap,Noto Sans,{fs},&H00FFFFFF,&H00FFFFFF,&H00141414,&H64000000,1,0,0,0,100,100,0,0,1,{ol},1,2,{m},{m},{mv},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n").format(
        w=w, h=h, fs=fs, ol=max(2, round(fs / 11)), m=round(w * 0.06), mv=round(h * 0.07))
    lines = ["Dialogue: 0,{},{},Cap,,0,0,0,,{}".format(_ass_time(a + shift), _ass_time(b + shift),
                                                       t.replace("{", "(").replace("}", ")").replace("\n", " "))
             for a, b, t in phrases(words)]
    pathlib.Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _filter_path(p):
    """Путь для фильтра ffmpeg (ass=…): двоеточия и кавычки экранируются."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def whoosh(path, secs=0.55):
    """Звук перехода: мягкий «вжух» — розовый шум, проходящий полосой частот, быстро нарастает и гаснет. Делается на месте."""
    if pathlib.Path(path).exists():
        return path
    run_ffmpeg(["-f", "lavfi", "-i", "anoisesrc=color=pink:duration={:.2f}:sample_rate=44100:amplitude=0.5".format(secs),
                "-af", "highpass=f=300,lowpass=f=3200,afade=t=in:d={:.2f}:curve=exp,afade=t=out:st={:.2f}:d={:.2f},"
                       "volume=0.35,aformat=channel_layouts=stereo".format(secs * 0.45, secs * 0.45, secs * 0.55),
                "-c:a", "pcm_s16le", path])
    return path


AUDIO_OUT = ["-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]
VIDEO_OUT = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", FPS]


def _audio_in(voice_file, secs, sfx=None, lead=0.0):
    """Вход звука для клипа: голос (дополненный тишиной до длины клипа) или тишина; sfx — звук перехода в начале,
    голос тогда вступает чуть позже (lead секунд), чтобы не наложиться на «вжух»."""
    if voice_file:
        ins, chain = ["-i", voice_file], "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={d}|{d},apad,atrim=0:{s:.2f}".format(
            d=int(lead * 1000), s=secs)
    else:
        ins, chain = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"], "[1:a]atrim=0:{:.2f}".format(secs)
    if sfx:
        return ins + ["-i", sfx], chain + "[v0];[2:a]apad,atrim=0:{s:.2f}[s0];[v0][s0]amix=inputs=2:duration=first:normalize=0[a]".format(s=secs)
    return ins, chain + "[a]"


def _caption_filter(ass):
    return ",ass='{}'".format(_filter_path(ass)) if ass else ""


def slide_clip(image, voice_file, secs, size, out, index=0, ass=None, sfx=None, lead=0.0):
    """Картинка → клип: медленный наезд (чётные сцены) или отъезд (нечётные), плавное появление и уход."""
    w, h = size
    frames = int(secs * FPS)
    zoom = "1+0.12*on/{}".format(frames) if index % 2 == 0 else "1.12-0.12*on/{}".format(frames)
    video = ("[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             "zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}{cap},"
             "fade=t=in:st=0:d=0.4,fade=t=out:st={fo:.2f}:d=0.4[v]").format(
        W=w * 2, H=h * 2, z=zoom, d=frames, w=w, h=h, fps=FPS, fo=max(0, secs - 0.4), cap=_caption_filter(ass))
    a_in, a_filter = _audio_in(voice_file, secs, sfx, lead)
    run_ffmpeg(["-loop", "1", "-i", image] + a_in + ["-filter_complex", video + ";" + a_filter, "-map", "[v]", "-map", "[a]",
               "-t", "{:.2f}".format(secs)] + VIDEO_OUT + AUDIO_OUT + [out])
    return out


def live_clip(video, voice_file, secs, size, out, ass=None, sfx=None, lead=0.0):
    """Живое видео от Qwen → клип нужной длины и размера со своим звуком (последний кадр замирает, если видео короче)."""
    w, h = size
    v = ("[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},"
         "tpad=stop_mode=clone:stop_duration={pad:.2f},trim=0:{s:.2f},setpts=PTS-STARTPTS{cap},"
         "fade=t=in:st=0:d=0.4,fade=t=out:st={fo:.2f}:d=0.4[v]").format(w=w, h=h, fps=FPS, pad=secs, s=secs, fo=max(0, secs - 0.4),
                                                                        cap=_caption_filter(ass))
    a_in, a_filter = _audio_in(voice_file, secs, sfx, lead)
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


LEAD = 0.3            # с: после звука перехода голос вступает чуть позже
PREVIEW_SECONDS = 20  # пробный кусок: первые сцены примерно на столько секунд


def scene_seconds(scene):
    """Примерная длина сцены по закадровому тексту (~14 знаков в секунду) — для пробного куска и цены."""
    return max(MIN_SCENE, min(20, len(scene.get("narration") or "") / 13.3 + TAIL + LEAD))   # 13,3 знака в секунду — замер


def preview_count(scenes, seconds=PREVIEW_SECONDS):
    """Сколько первых сцен дают ~20 секунд."""
    total = 0.0
    for i, sc in enumerate(scenes):
        total += scene_seconds(sc)
        if total >= seconds:
            return i + 1
    return len(scenes)


def background(place, look, ratio, work):
    """Фон места для мультфильма (цветные стили): одна картинка на место, без людей — человечков рисует мультипликатор."""
    import hashlib

    from . import stickman_styles as ST

    path = pathlib.Path(work) / "bg-{}.png".format(hashlib.sha1(place.encode("utf-8")).hexdigest()[:10])
    if not path.exists():
        world = ST.STYLES.get(look, ST.STYLES[ST.DEFAULT])["world"]
        made = qm.image("{}. Empty scene, no people, no characters, wide establishing shot, ground in the lower part of the frame. "
                        "Style: {}. No text, letters or numbers.".format(place, world), ratio)[0]
        shutil.copyfile(made, path)
    return path


def make_scene(i, scene, style, ratio, mode, size, work, progress=lambda text: None, captions=True, sfx=True, look=None, hold=0.0):
    """Одна сцена целиком: картинка, голос, субтитры, клип. Всё лежит в папке проекта: прерванный ролик
    продолжается с того же места, готовое не делается и не оплачивается второй раз."""
    work = pathlib.Path(work)
    clip = work / "clip{:02d}.mp4".format(i)
    if clip.exists() and clip.stat().st_size > 0:
        progress("сцена {} уже готова".format(i + 1))
        return clip
    image = work / "image{:02d}.png".format(i)
    if mode != "anim" and not image.exists():
        prompt = scene["picture"] + (". " + style if style else "")
        made = qm.image(prompt, ratio)[0]
        shutil.copyfile(made, image)
    voice_file = work / "voice{:02d}.mp3".format(i)
    words_file = work / "words{:02d}.json".format(i)
    if scene["narration"] and voice_file.exists() and words_file.exists():
        words = [tuple(x) for x in json.loads(words_file.read_text(encoding="utf-8"))]
    else:
        voice_file, words, _exact = narrate_words(scene["narration"], voice_file)
        if voice_file:
            words_file.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    lead = LEAD if (sfx and i > 0 and voice_file) else 0.0
    secs = max(MIN_SCENE, (duration(voice_file) + TAIL + lead) if voice_file else MIN_SCENE) + hold
    ass = captions_ass(words, size, work / "captions{:02d}.ass".format(i), shift=lead) if (captions and words) else None
    whoosh_file = whoosh(work / "whoosh.wav") if (sfx and i > 0) else None
    part = work / "clip{:02d}.part.mp4".format(i)
    if mode == "anim":
        from . import animator

        bg = background(scene["place"], look, ratio, work) if (look in BG_LOOKS and scene.get("place")) else None
        spec = dict(scene.get("anim") or {})
        for k in ("shot", "beat"):                       # план и тип сцены — камере и звукам мультипликатора
            if scene.get(k) and not spec.get(k):
                spec[k] = scene[k]
        animator.anim_clip(spec, look or "classic_light", voice_file, secs, size, part, ass, whoosh_file, lead, bg,
                           words)
    elif mode == "live":
        task = qm.video_start(scene.get("video") or scene["picture"], str(image), seconds=min(15, int(secs + 0.99)), resolution="720P")
        raw = qm.video_wait(task, "сцена-{}".format(i + 1))
        try:
            live_clip(raw, voice_file, secs, size, part, ass, whoosh_file, lead)
        finally:
            pathlib.Path(raw).unlink(missing_ok=True)       # сырой клип сцены в «Видео/Chloe» не нужен
    else:
        slide_clip(image, voice_file, secs, size, part, i, ass, whoosh_file, lead)
    os.replace(part, clip)
    progress("сцена {} готова".format(i + 1))
    return clip


PROJECTS = qm.VIDEO_DIR / "проекты"


def new_project(title, scenes, style="", ratio="16:9", mode="slides", meta=None):
    """Папка проекта ролика: сценарий и всё сделанное по сценам — чтобы после пробного куска доделать весь ролик."""
    folder = PROJECTS / "{}-{}".format(time.strftime("%Y%m%d-%H%M%S"), qm._slug(title or scenes[0]["picture"]))
    folder.mkdir(parents=True, exist_ok=True)
    data = dict(meta or {}, title=title, scenes=scenes, style=style, ratio=ratio, mode=mode, created=time.time())
    (folder / "project.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return folder


def load_project(folder=None):
    """Проект по папке; без папки — последний."""
    if folder is None:
        found = sorted(PROJECTS.glob("*/project.json")) if PROJECTS.exists() else []
        if not found:
            raise StudioError("нет начатых роликов")
        folder = found[-1].parent
    folder = pathlib.Path(folder)
    try:
        data = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StudioError("нет такого проекта ролика") from None
    data["folder"] = folder
    return data


def make_film(title, scenes, style="", ratio="16:9", mode="slides", progress=lambda text: None, workers=3,
              project=None, upto=None, captions=True, sfx=True, music=True, look=None):
    """Ролик (или его первые upto сцен — пробный кусок). project — папка проекта: готовые сцены берутся оттуда.
    Возвращает путь к mp4 в «Видео/Chloe»."""
    scenes = clean_scenes(scenes)
    if not scenes:
        raise StudioError("нет сцен: нужна хотя бы одна с описанием картинки")
    ratio = ratio if ratio in FRAMES else "16:9"
    size = FRAMES[ratio]
    ffmpeg()                                   # нет ffmpeg — скажем сразу, а не после минут рисования
    count = min(len(scenes), upto or len(scenes))
    with tempfile.TemporaryDirectory(prefix="chloe-film-") as tmp:
        work = pathlib.Path(project) if project else pathlib.Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        cuts = transition_plan(scenes) if sfx else set()
        hold = ending_hold(scenes) if count == len(scenes) else 0.0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = [pool.submit(make_scene, i, s, style, ratio, mode, size, work, progress, captions, i in cuts, look,
                                hold if i == len(scenes) - 1 else 0.0)
                    for i, s in enumerate(scenes[:count])]
            try:
                clips = [j.result() for j in jobs]
            except qm.MediaError as e:
                for j in jobs:
                    j.cancel()
                raise StudioError(str(e)) from None
        qm.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        tail = "-проба" if count < len(scenes) else ""
        out = qm.VIDEO_DIR / "{}-{}{}.mp4".format(time.strftime("%Y%m%d-%H%M%S"), qm._slug(title or scenes[0]["picture"]), tail)
        joined = work / "joined.mp4"
        join(clips, joined)
        track = music_track() if music else None
        mixed = work / "mixed.mp4"
        if track:
            add_music(joined, track, mixed)
        else:
            os.replace(joined, mixed)
        try:
            master(mixed, out)
        except (StudioError, OSError) as e:      # громкость не выровнялась — ролик всё равно отдаём
            log.info("мастеринг не вышел: %s", e)
            shutil.copyfile(mixed, out)
        joined.unlink(missing_ok=True)
        mixed.unlink(missing_ok=True)
        if project:
            hear(out, work, [duration(c) for c in clips])
    return out


def transition_plan(scenes):
    """На каких стыках звучит «вжух» (номера сцен). Не на каждом: только где меняется этап сюжета или сцена — перемена,
    путь, поворот; никогда два стыка подряд, не больше двух за 30 секунд, перед тихой сценой — ничего.
    Без пометок этапов — через стык."""
    marked = any(sc.get("stage") or sc.get("beat") for sc in scenes)
    plan, starts, t = set(), [], 0.0
    for i, sc in enumerate(scenes):
        starts.append(t)
        t += scene_seconds(sc)
        if i == 0:
            continue
        if marked:
            want = sc.get("stage") != scenes[i - 1].get("stage") or sc.get("beat") in ("change", "travel", "turn")
        else:
            want = i % 2 == 1
        if sc.get("beat") == "quiet" or (i - 1) in plan:
            want = False
        if want and sum(1 for j in plan if starts[i] - starts[j] < 30) < 2:
            plan.add(i)
    return plan


def ending_hold(scenes):
    """Финалу — свои секунды после последней фразы: до минуты — 2 с, длиннее — 4 с (вместе с обычной паузой)."""
    total = sum(scene_seconds(sc) for sc in scenes)
    return max(0.0, (2.0 if total <= 70 else 4.0) - TAIL)


LOUDNESS = -14.0     # LUFS: как у роликов в сети; пики не выше -1,5 dBTP (AAC поднимает пики)


def master(video, out):
    """Громкость ролика к единой норме (два прохода loudnorm): все ролики Хлои звучат одинаково громко, без перегруза.
    Картинка копируется без перекодирования."""
    target = "I={}:TP=-1.5:LRA=11".format(LOUDNESS)
    err = run_ffmpeg(["-i", video, "-vn", "-af", "loudnorm={}:print_format=json".format(target), "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err)
    if not m:
        raise StudioError("loudnorm не измерил громкость")
    v = json.loads(m.group(0))
    if float(v["input_i"]) < -70:                  # тишина — нормировать нечего
        shutil.copyfile(video, out)
        return out
    second = ("loudnorm={t}:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:"
              "measured_thresh={input_thresh}:offset={target_offset}:linear=true").format(t=target, **v)
    run_ffmpeg(["-i", video, "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af", second + ",aresample=44100"] + AUDIO_OUT +
               ["-movflags", "+faststart", out])
    return out


def hear(video, folder, scenes=None):
    """Хлоя слушает готовый ролик: громкость, перегруз, провалы тишины, сцены намного громче или тише остальных
    (scenes — длины сцен в секундах) — отчёт в папку проекта (проверка-звука.json). Ошибка проверки ролик не ломает."""
    from . import sfx

    wav = pathlib.Path(folder) / "heard.wav"
    try:
        run_ffmpeg(["-i", video, "-vn", "-ac", "2", "-ar", str(sfx.SR), "-c:a", "pcm_s16le", wav])
        report = sfx.listen(wav, scenes)
        (pathlib.Path(folder) / "проверка-звука.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        if report["notes"]:
            log.info("звук ролика: %s", "; ".join(report["notes"]))
        return report
    except (StudioError, OSError, ValueError) as e:
        log.info("не смогла послушать ролик: %s", e)
        return None
    finally:
        wav.unlink(missing_ok=True)


def music_track():
    """Фоновая музыка: первый файл из «Музыка/Chloe» (кладёт пользователь). Нет папки — ролик без музыки."""
    from .config import user_dir

    folder = user_dir("MUSIC", "Music") / "Chloe"
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".ogg", ".wav", ".flac")) if folder.exists() else []
    return files[0] if files else None


def add_music(video, track, out):
    """Музыка под голосом: тихо, по кругу, приглушается, когда звучит голос, плавно уходит в конце."""
    secs = duration(video)
    run_ffmpeg(["-i", video, "-stream_loop", "-1", "-i", track, "-filter_complex",
                "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.16,atrim=0:{s:.2f},"
                "afade=t=in:d=1.5,afade=t=out:st={fo:.2f}:d=2[m];"
                "[0:a]asplit=2[v][key];[m][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[md];"
                "[v][md]amix=inputs=2:duration=first:normalize=0[a]".format(s=secs, fo=max(0, secs - 2)),
                "-map", "0:v", "-map", "[a]", "-c:v", "copy"] + AUDIO_OUT + ["-movflags", "+faststart", out])
    return out
