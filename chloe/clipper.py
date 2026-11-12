"""Нарезчик клипов из игр и стримов → вертикальные Shorts (как у сервисов-клипперов, но на этом компьютере и бесплатно).

Длинная запись (геймплей, стрим с веб-камерой) → лучшие моменты → готовые Shorts 1080×1920 с субтитрами по словам:
  • моменты: всплески звука (выстрелы, взрывы, крик), эмоции стримера в речи (слова, смех, громкость), резкое движение
    картинки; у каждого момента — разгон до пика и пара секунд после, границы не режут фразу;
  • раскладка: есть веб-камера (Хлоя находит её сама — лицо, которое всё время в одном месте кадра) — камера сверху,
    игра снизу; нет — игра на всю ширину, крупнее, на размытом фоне;
  • субтитры по 2–4 слова, текущее слово подсвечено (распознавание — faster-whisper на этом компьютере);
  • крючок: надпись первые секунды и зум-рывок на пике; громкость — к норме YouTube (−14 LUFS);
  • clips.txt: названия, описание, хэштеги (#shorts и игра), предупреждение про музыку (Content ID).
"""
import json
import math
import pathlib
import re
import subprocess

import numpy as np

from . import shorts as SH

FPS = 30
HOP = 0.1                                  # шаг анализа, с
LENGTH = (15.0, 45.0)                      # длина клипа: от и до (с)
PRE, POST = 11.0, 4.0                      # разгон до пика и хвост после него (с)
CAM_H = 0.38                               # доля высоты Shorts под веб-камеру (раскладка «стример»)
FIT_ZOOM = 1.8                             # игра без камеры: крупнее ширины экрана (края обрезаются), ~60 % высоты
PUNCH = 0.1                                # зум-рывок на пике (доля)
EXCITE = ("офиг", "охрен", "ничего себе", "вау", "ого", "блин", "чёрт", "черт", "капец", "жесть", "погнали", "давай",
          "нет нет", "ааа", "ахах", "хаха", "смотри", "убил", "взорв", "lol", "omg", "wow", "no way", "let's go", "lets go",
          "what", "bro", "holy", "insane", "crazy", "oh my", "haha", "dude", "wtf", "yes", "no no")
MODEL_DIR = "models/whisper"


class ClipperError(Exception):
    pass


# --- разбор записи ---
def probe(video):
    """Длительность, размер кадра и частота кадров записи."""
    from . import studio

    p = subprocess.run([studio.ffmpeg(), "-hide_banner", "-i", str(video)], capture_output=True, text=True)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", p.stderr)
    f = re.search(r"([\d.]+) fps", p.stderr)
    if not d or not m:
        raise ClipperError("не читается видео")
    secs = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
    return {"secs": secs, "w": int(m.group(1)), "h": int(m.group(2)), "fps": float(f.group(1)) if f else 30.0,
            "audio": "Audio:" in p.stderr}


def audio_curve(video, hop=HOP):
    """Громкость звука по шагам hop (среднеквадратичная, 0..1)."""
    from . import studio

    sr = 16000
    r = subprocess.run([studio.ffmpeg(), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True, timeout=3600)
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768
    n = int(len(a) / (sr * hop))
    if n == 0:
        return np.zeros(0)
    k = int(sr * hop)
    return np.sqrt(np.mean(a[:n * k].reshape(n, k) ** 2, axis=1))


def motion_curve(video, hop=HOP):
    """Сколько меняется картинка (0..1) по шагам hop — по крошечным серым кадрам; и где смена плана (резкий скачок)."""
    from . import studio

    w, h, fps = 64, 36, 1 / hop
    r = subprocess.run([studio.ffmpeg(), "-v", "error", "-i", str(video), "-vf", "fps={},scale={}:{},format=gray".format(fps, w, h),
                        "-f", "rawvideo", "-"], capture_output=True, timeout=3600)
    data = np.frombuffer(r.stdout, dtype=np.uint8)
    n = len(data) // (w * h)
    if n < 2:
        return np.zeros(max(n, 0)), []
    fr = data[:n * w * h].reshape(n, h, w).astype(np.float32) / 255
    d = np.concatenate([[0.0], np.mean(np.abs(np.diff(fr, axis=0)), axis=(1, 2))])
    thr = max(0.12, float(np.percentile(d, 99.5)))
    cuts = [round(i * hop, 2) for i in range(1, n) if d[i] > thr]
    return d, cuts


def transcribe(video, cache=None, lang=None, model="small", progress=None):
    """Речь записи по словам: [{"s", "e", "w"}] — faster-whisper на этом компьютере; кэш — JSON рядом (второй раз не
    распознаётся). Нет faster-whisper — пустой список (клипы без субтитров)."""
    if cache and pathlib.Path(cache).exists():
        return json.loads(pathlib.Path(cache).read_text(encoding="utf-8"))
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []
    from .config import DATA

    m = WhisperModel(model, device="cpu", compute_type="int8", download_root=str(DATA / MODEL_DIR))
    from . import studio

    r = subprocess.run([studio.ffmpeg(), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                       capture_output=True, timeout=3600)                 # звук — сами (без av: его новые версии ломаются)
    pcm = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768
    segs, info = m.transcribe(pcm, language=lang, word_timestamps=True, vad_filter=True, beam_size=1)
    words = []
    for seg in segs:
        for w in seg.words or []:
            words.append({"s": round(w.start, 2), "e": round(w.end, 2), "w": w.word.strip()})
        if progress:
            progress(seg.end)
    if cache:
        pathlib.Path(cache).write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words


def speech_curve(words, n, hop=HOP):
    """Эмоции стримера по шагам: восклицательные слова и смех, частая речь (тараторит — значит, что-то происходит)."""
    out = np.zeros(n)
    for w in words:
        i = int(w["s"] / hop)
        if not 0 <= i < n:
            continue
        low = w["w"].lower()
        hot = any(k in low for k in EXCITE) or "!" in low or re.search(r"(а{3,}|о{3,}|a{3,}|o{3,})", low)
        out[i] += 1.0 if hot else 0.15
    k = int(2.0 / hop)
    return np.convolve(out, np.ones(k) / k, mode="same") * k / 3


def _norm(x):
    p = float(np.percentile(x, 97)) if len(x) else 0.0
    return np.clip(x / p, 0, 1.5) if p > 0 else x


def score_curve(audio, motion, speech):
    """Оценка «насколько залетит» по шагам: всплеск звука над фоном, движение, эмоции речи."""
    n = max(len(audio), len(motion), len(speech))
    pad = [np.pad(np.asarray(x, dtype=float), (0, n - len(x))) for x in (audio, motion, speech)]
    a, m, s = pad
    k = int(8 / HOP) | 1                                            # «фон» звука — медиана за 8 с
    bg = np.array([np.median(a[max(0, i - k // 2):i + k // 2 + 1]) for i in range(0, n)]) if n < 200000 else a
    burst = np.clip(a - bg, 0, None)
    sc = 0.45 * _norm(burst) + 0.2 * _norm(m) + 0.35 * _norm(s)
    return SH._smooth(sc, 0.6 / HOP)


def _snap(t, words, after):
    """Сдвинуть границу клипа в паузу между словами (не резать фразу): after — граница-конец (сдвиг вперёд)."""
    for w in words:
        if w["s"] < t < w["e"]:
            return w["e"] + 0.15 if after else max(0.0, w["s"] - 0.15)
    return t


def pick_moments(score, words, secs, count=5, length=30.0):
    """Лучшие моменты: пики оценки → отрезок с разгоном до пика и хвостом после, по фразам, без пересечений.
    [(начало, конец, пик, оценка)]."""
    lo, hi = LENGTH
    length = min(hi, max(lo, float(length)))
    order = np.argsort(score)[::-1]
    out = []
    for i in order:
        peak = i * HOP
        if any(a - 2 <= peak <= b + 2 for a, b, _p, _s in out):
            continue
        pre = min(PRE, length - POST)
        a = max(0.0, peak - pre)
        b = min(secs, a + length)
        a = max(0.0, b - length)
        a, b = _snap(a, words, False), _snap(b, words, True)
        if b - a < lo * 0.8 or any(not (b <= x or a >= y) for x, y, _p, _s in out):
            continue
        out.append((round(a, 2), round(min(b, secs), 2), round(peak, 2), round(float(score[i]), 3)))
        if len(out) >= count:
            break
    return sorted(out, key=lambda m: -m[3])


# --- веб-камера стримера ---
FACE_MODEL = ("https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/"
              "blaze_face_short_range.tflite")


def _face_model():
    import urllib.request

    from .config import DATA

    p = DATA / "models" / "blaze_face_short_range.tflite"
    if not p.exists() or p.stat().st_size < 100_000:
        p.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(FACE_MODEL, timeout=120) as r, open(p.with_suffix(".part"), "wb") as f:
            f.write(r.read())
        p.with_suffix(".part").replace(p)
    return p


def find_facecam(video, secs, samples=12):
    """Где веб-камера стримера: лицо, которое на большинстве кадров стоит в одном и том же месте (герои игры бегают,
    камера — нет). Возвращает прямоугольник камеры (x, y, ширина, высота в долях кадра) или None."""
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
    except ImportError:
        return None
    from . import studio

    try:
        det = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(_face_model())), min_detection_confidence=0.6))
    except Exception:                                                  # noqa: BLE001 — нет модели (нет сети) — без камеры
        return None
    W, H, tw, th = 1920, 1080, 480, 270                               # лицо в камере мелкое — ищем по кускам 480×270
    boxes = []
    for k in range(samples):
        t = secs * (k + 0.5) / samples
        r = subprocess.run([studio.ffmpeg(), "-v", "error", "-ss", "{:.2f}".format(t), "-i", str(video), "-frames:v", "1",
                            "-vf", "scale={}:{}".format(W, H), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
        if len(r.stdout) < W * H * 3:
            continue
        img = np.frombuffer(r.stdout[:W * H * 3], dtype=np.uint8).reshape(H, W, 3)
        found = []
        for y0 in range(0, H - th + 1, th // 2):
            for x0 in range(0, W - tw + 1, tw // 2):
                res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img[y0:y0 + th, x0:x0 + tw])))
                for d in res.detections:
                    bb = d.bounding_box
                    found.append(((x0 + bb.origin_x) / W, (y0 + bb.origin_y) / H, bb.width / W, bb.height / H))
        boxes.append(found)
    det.close()
    return facecam_rect(boxes)


def facecam_rect(boxes, aspect=1080 / (1920 * CAM_H), frame=(1920, 1080)):
    """Найденные лица по кадрам [[(x, y, w, h)…]…] → прямоугольник веб-камеры (доли кадра) или None.
    Камера — лицо, которое почти на всех кадрах в одном месте; кадр вокруг него — голова и плечи, в пропорциях
    верхней панели Shorts."""
    W, H = frame
    flat = [b for fr in boxes for b in fr]
    best = None
    for b in flat:
        cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
        near = [[o for o in fr if abs(o[0] + o[2] / 2 - cx) < 0.06 and abs(o[1] + o[3] / 2 - cy) < 0.07] for fr in boxes]
        hits = sum(1 for m in near if m)
        if hits >= max(3, len(boxes) * 0.6) and (best is None or hits > best[0]):
            best = (hits, [m[0] for m in near if m])
    if not best:
        return None
    ms = best[1]
    fx = float(np.median([m[0] + m[2] / 2 for m in ms])) * W
    fy = float(np.median([m[1] + m[3] / 2 for m in ms])) * H
    fw = float(np.median([m[2] for m in ms])) * W
    rw = min(W * 0.45, max(W * 0.15, fw * 6.0))
    rh = rw / aspect
    x = min(max(0.0, fx - rw / 2), W - rw)
    y = min(max(0.0, fy + rh * 0.12 - rh / 2), H - rh)
    return (x / W, y / H, rw / W, rh / H)


# --- кадр Shorts ---
def _src_surface(raw, W, H, cairo):
    return cairo.ImageSurface.create_for_data(bytearray(raw), cairo.FORMAT_RGB24, W, H, W * 4)


def _cover(c, src, rect, box, cairo, zoom=1.0):
    """Нарисовать часть кадра rect (x, y, w, h в пикселях источника) так, чтобы она заполнила box (x, y, w, h) на экране."""
    sx, sy, sw, sh = rect
    bx, by, bw, bh = box
    s = max(bw / sw, bh / sh) * zoom
    c.save()
    c.rectangle(bx, by, bw, bh)
    c.clip()
    c.translate(bx + bw / 2, by + bh / 2)
    c.scale(s, s)
    c.translate(-(sx + sw / 2), -(sy + sh / 2))
    c.set_source_surface(src, 0, 0)
    c.get_source().set_filter(cairo.FILTER_GOOD)
    c.paint()
    c.restore()


def game_x(cam, W, gw):
    """Где вырезать игру для нижней панели: по центру, но так, чтобы угол с веб-камерой не попал (камера справа —
    сдвиг влево, слева — вправо), не дальше краёв кадра."""
    x = (W - gw) / 2
    if cam:
        cl, cr = cam[0] * W, (cam[0] + cam[2]) * W
        if cr > x and cl < x + gw:                                    # камера заходит в вырезку
            x = cl - gw if (cl + cr) / 2 > W / 2 else cr
    return min(max(0.0, x), W - gw)


def compose(c, src, W, H, layout, cam, zoom, cairo):
    """Кадр 1080×1920: «стример» — камера сверху, игра снизу; «игра» — игра крупнее ширины экрана на размытом фоне."""
    OW, OH = SH.SIZE
    if layout == "streamer" and cam:
        cx, cy, cw, ch = cam
        top = int(OH * CAM_H)
        _cover(c, src, (cx * W, cy * H, cw * W, ch * H), (0, 0, OW, top), cairo)
        gw = W * 0.62                                                # игра: средняя часть кадра, но в стороне от камеры
        gx = game_x(cam, W, gw)
        _cover(c, src, (gx, 0, gw, H), (0, top, OW, OH - top), cairo, zoom)
        c.set_source_rgb(0.05, 0.05, 0.07)
        c.rectangle(0, top - 3, OW, 6)
        c.fill()
        return top
    small = cairo.ImageSurface(cairo.FORMAT_RGB24, 32, 18)            # фон: тот же кадр, размытый и тёмный
    sc = cairo.Context(small)
    sc.scale(32 / W, 18 / H)
    sc.set_source_surface(src, 0, 0)
    sc.paint()
    _cover(c, small, (32 * 0.3, 0, 32 * 0.4, 18), (0, 0, OW, OH), cairo)
    c.set_source_rgba(0, 0, 0, 0.5)
    c.paint()
    gh = OW / (W / H) * FIT_ZOOM
    gy = (OH - gh) / 2
    _cover(c, src, ((W - W / FIT_ZOOM) / 2, 0, W / FIT_ZOOM, H), (0, gy, OW, gh), cairo, zoom)
    return int(gy + gh)


def caption_groups(words, a, b, size=3):
    """Слова клипа группами по 2–4 (не больше 22 букв): [(начало, конец, [слова со временем])]."""
    ws = [w for w in words if a <= w["s"] < b and w["w"]]
    out, cur = [], []
    for w in ws:
        if cur and (len(cur) >= size or sum(len(x["w"]) for x in cur) + len(w["w"]) > 22 or w["s"] - cur[-1]["e"] > 0.6):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [(g[0]["s"], max(g[-1]["e"], g[0]["s"] + 0.4), g) for g in out]


def draw_caption(c, group, t, y):
    """Субтитр: слова группы крупно, текущее — жёлтым и чуть крупнее (подпрыгивает)."""
    _s, _e, ws = group
    size = 82
    SH._font(c, size)
    full = c.text_extents(" ".join(w["w"].upper() for w in ws)).x_advance * 1.1
    if full * 1.12 > SH.SIZE[0] * 0.86:                               # не влезает — шрифт меньше (с запасом на «прыжок»)
        size = size * SH.SIZE[0] * 0.86 / (full * 1.12)
        SH._font(c, size)
    widths = [c.text_extents(w["w"].upper()).x_advance for w in ws]
    space = c.text_extents(" ").x_advance * 1.4 + max(widths) * 0.07   # с запасом: текущее слово «подпрыгивает» на 12 %
    x = (SH.SIZE[0] - (sum(widths) + space * (len(ws) - 1))) / 2
    for w, wd in zip(ws, widths):
        now = w["s"] <= t < max(w["e"], w["s"] + 0.15)
        k = 1.12 if now else 1.0
        c.save()
        c.translate(x + wd / 2, y)
        c.scale(k, k)
        c.move_to(-wd / 2, 0)
        c.text_path(w["w"].upper())
        c.set_source_rgb(0.04, 0.04, 0.06)
        c.set_line_width(size * 0.2)
        c.set_line_join(1)
        c.stroke_preserve()
        c.set_source_rgb(*(SH.ACCENT if now else (1, 1, 1)))
        c.fill()
        c.restore()
        x += wd + space


def render_clip(video, out, a, b, peak, layout, cam, words, hook, info, progress=None):
    """Один клип → mp4 1080×1920: кадры через cairo, звук — тот же отрезок с плавными краями и громкостью −14 LUFS."""
    import cairo

    from . import studio

    W = 1920
    H = int(round(info["h"] * W / info["w"] / 2) * 2)
    OW, OH = SH.SIZE
    dur = b - a
    groups = caption_groups(words, a, b)
    acc = SH.accent_word(hook) if hook else None
    aud = [] if not info.get("audio") else ["-ss", "{:.3f}".format(a), "-t", "{:.3f}".format(dur), "-i", str(video)]
    af = "afade=t=in:d=0.08,afade=t=out:st={:.2f}:d=0.4,loudnorm=I=-14:TP=-1.5:LRA=11".format(max(0, dur - 0.4))
    enc = subprocess.Popen([studio.ffmpeg(), "-hide_banner", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
                            "-s", "{}x{}".format(OW, OH), "-r", str(FPS), "-i", "-"] + aud +
                           (["-map", "0:v", "-map", "1:a", "-af", af] if aud else []) + ["-t", "{:.3f}".format(dur)] +
                           [str(x) for x in studio.VIDEO_OUT[:-2]] + ["-r", str(FPS)] +
                           ([str(x) for x in studio.AUDIO_OUT] if aud else []) + ["-movflags", "+faststart", str(out)],
                           stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    dec = subprocess.Popen([studio.ffmpeg(), "-v", "error", "-ss", "{:.3f}".format(a), "-i", str(video), "-t", "{:.3f}".format(dur),
                            "-vf", "fps={},scale={}:{}".format(FPS, W, H), "-f", "rawvideo", "-pix_fmt", "bgra", "-"],
                           stdout=subprocess.PIPE)
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, OW, OH)
    c = cairo.Context(surf)
    n = int(round(dur * FPS))
    try:
        for k in range(n):
            raw = dec.stdout.read(W * H * 4)
            if len(raw) < W * H * 4:
                break
            t = a + k / FPS
            zoom = 1.0 + PUNCH * max(0.0, 1 - abs(t - peak) / 0.35)      # зум-рывок на пике
            c.set_source_rgb(0, 0, 0)
            c.paint()
            bottom = compose(c, _src_surface(raw, W, H, cairo), W, H, layout, cam, zoom, cairo)
            if hook and k / FPS < SH.HOOK_SECS:
                tt = k / FPS
                alpha = 1.0 if tt < SH.HOOK_SECS - 0.3 else max(0.0, (SH.HOOK_SECS - tt) / 0.3)
                SH.draw_text(c, hook, OH * (0.04 if layout == "streamer" else 0.12), 104, acc, alpha, 0.85 + 0.15 * min(1.0, tt / 0.12))
            g = next((g for g in groups if g[0] <= t < g[1]), None)
            if g:
                y = OH * CAM_H + 110 if layout == "streamer" else min(OH * 0.68, bottom + 120)
                draw_caption(c, g, t, y)
            surf.flush()
            enc.stdin.write(bytes(surf.get_data()))
            if progress and k % (FPS * 5) == 0:
                progress(k, n)
        enc.stdin.close()
        err = enc.stderr.read().decode("utf-8", "replace")
        if enc.wait(timeout=600) != 0:
            raise ClipperError("ffmpeg: " + (err.strip().splitlines() or ["ошибка"])[-1][:200])
    finally:
        dec.stdout.close()
        dec.wait()
    return out


# --- названия, крючки ---
META = """Ты делаешь YouTube Shorts из записи игры{game}. Для каждого клипа по его речи придумай:
"hook" — надпись на первые 2 секунды (до 5 слов, интрига, только то, что правда есть в клипе),
"title" — название до 70 знаков (крючок, без обмана, без КАПСА целиком).
Ответь ТОЛЬКО JSON: {{"clips": [{{"hook": "…", "title": "…"}}, …]}} — ровно {n} штук по порядку.

КЛИПЫ (речь в каждом):
{parts}"""


def clip_meta(texts, game="", ask=None):
    """Крючки и названия клипов: от модели; нет модели — по самым громким словам клипа."""
    fallback = [{"hook": (" ".join(t.split()[:5]) or "Смотри до конца").strip(" ,."), "title": (t[:60] or "Момент из игры")}
                for t in texts]
    if ask is False:
        return fallback
    if ask is None:
        try:
            from .screenplay import model_ask as ask
        except ImportError:
            return fallback
    prompt = META.format(game=" " + game if game else "", n=len(texts),
                         parts="\n".join("{}. {}".format(i + 1, t[:600] or "(без слов)") for i, t in enumerate(texts)))
    try:
        try:
            reply = ask(prompt, False)
        except TypeError:
            reply = ask(prompt)
        m = re.search(r"\{.*\}", reply or "", re.S)
        got = json.loads(m.group(0)).get("clips") if m else None
    except Exception as e:                                             # noqa: BLE001 — без модели — по словам клипа
        print("[нарезчик: модель — {}]".format(str(e)[:80]))
        got = None
    out = []
    for i, fb in enumerate(fallback):
        g = got[i] if isinstance(got, list) and i < len(got) and isinstance(got[i], dict) else {}
        hook = str(g.get("hook") or "").strip()
        out.append({"hook": hook if hook and len(hook.split()) <= 7 else fb["hook"],
                    "title": str(g.get("title") or fb["title"]).strip()[:90]})
    return out


NOTES = """НАРЕЗКА: {name} — {n} Shorts

{items}
ПЕРЕД ЗАГРУЗКОЙ:
[ ] Музыка в игре (радио в машине, клубы, заставки) ловится Content ID — такой клип лучше не выкладывать или приглушить
    музыку; Хлоя пометила клипы, где играет музыка без слов
[ ] Rockstar разрешает ролики с геймплеем (в том числе с монетизацией) в разумных пределах — без утечек и спойлеров
    до выхода игры; делай свой комментарий и монтаж: YouTube не платит за «перезалив» чужого видео
[ ] Выкладывай по 1–3 клипа в день; в описании — ссылка на полный стрим/ролик (в Shorts: «Связанное видео»)
"""


def music_suspect(audio, words, a, b, hop=HOP):
    """Похоже ли, что в клипе долго звучит музыка без речи (радио, заставка): ровный громкий звук и почти нет слов."""
    seg = audio[int(a / hop):int(b / hop)]
    if len(seg) < 10:
        return False
    talk = sum(1 for w in words if a <= w["s"] < b) / max(1.0, b - a)
    steady = float(np.mean(seg > np.percentile(seg, 50) * 0.7))
    return talk < 0.4 and steady > 0.85 and float(np.median(seg)) > 0.04


def clip(video, out_dir=None, count=5, length=30.0, game="", layout="auto", lang=None, ask=None, progress=print):
    """Запись → лучшие моменты → Shorts в out_dir (по умолчанию — рядом с записью, папка «<имя>-shorts») + clips.txt.
    Возвращает [(путь, начало, конец, оценка, название)]."""
    video = pathlib.Path(video)
    info = probe(video)
    out_dir = pathlib.Path(out_dir or video.with_name(video.stem + "-shorts"))
    out_dir.mkdir(parents=True, exist_ok=True)
    progress("Слушаю и смотрю запись ({:.0f} мин)…".format(info["secs"] / 60))
    audio = audio_curve(video) if info["audio"] else np.zeros(int(info["secs"] / HOP))
    motion, _cuts = motion_curve(video)
    words = transcribe(video, out_dir / "речь.json", lang) if info["audio"] else []
    speech = speech_curve(words, max(len(audio), len(motion)))
    score = score_curve(audio, motion, speech)
    moments = pick_moments(score, words, info["secs"], count, length)
    if not moments:
        raise ClipperError("не нашлось моментов (запись слишком короткая?)")
    cam = find_facecam(video, info["secs"]) if layout in ("auto", "streamer") else None
    lay = "streamer" if cam else "game"
    texts = [" ".join(w["w"] for w in words if a <= w["s"] < b) for a, b, _p, _s in moments]
    meta = clip_meta(texts, game, ask)
    made = []
    for i, ((a, b, peak, sc), m) in enumerate(zip(moments, meta), 1):
        out = out_dir / "clip-{:02d}.mp4".format(i)
        progress("Клип {} из {}: {:.0f}–{:.0f} с".format(i, len(moments), a, b))
        render_clip(video, out, a, b, peak, lay, cam, words, m["hook"], info)
        made.append((out, a, b, sc, m["title"], music_suspect(audio, words, a, b)))
    tags = ["#shorts"] + (["#" + re.sub(r"\W", "", game)] if game else [])
    items = ""
    for path, a, b, sc, title, music in made:
        items += "{}  ({}–{}, оценка {:.2f}){}\n  НАЗВАНИЕ: {}\n  ОПИСАНИЕ: {} {}\n\n".format(
            path.name, _ts(a), _ts(b), sc, "  ⚠ похоже на музыку — проверь Content ID" if music else "", title, title,
            " ".join(tags))
    (out_dir / "clips.txt").write_text(NOTES.format(name=video.name, n=len(made), items=items), encoding="utf-8")
    return made


def _ts(t):
    t = int(t)
    return "{}:{:02d}:{:02d}".format(t // 3600, t // 60 % 60, t % 60) if t >= 3600 else "{}:{:02d}".format(t // 60, t % 60)
