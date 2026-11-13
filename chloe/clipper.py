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
SAFE_TOP = 120                             # крючок не выше 120 px: сверху экрана значки приложения Shorts
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
    """Эмоции в речи по шагам: восклицательные слова, смех, растянутые «ааа». Обычная речь баллов не даёт — ровный
    закадровый голос (пояснения, пересказ) не делает момент интересным."""
    out = np.zeros(n)
    for w in words:
        i = int(w["s"] / hop)
        if not 0 <= i < n:
            continue
        low = w["w"].lower()
        hot = any(k in low for k in EXCITE) or "!" in low or re.search(r"(а{3,}|о{3,}|a{3,}|o{3,})", low)
        out[i] += 1.0 if hot else 0.0
    k = int(2.0 / hop)
    return np.convolve(out, np.ones(k) / k, mode="same") * k / 3


def _norm(x):
    p = float(np.percentile(x, 97)) if len(x) else 0.0
    return np.clip(x / p, 0, 1.5) if p > 0 else x


def onset_curve(video, hop=HOP):
    """Звук боя по шагам: сколько резких ударов (всплеск высоких частот относительно предыдущих 25 мс) — удары мечом,
    выстрелы, взрывы, звон; ровная музыка и голос дают мало. 0..1 по каждой секунде."""
    from . import studio

    sr, step, size = 16000, 400, 512
    r = subprocess.run([studio.ffmpeg(), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True, timeout=3600)
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768
    nfr = (len(a) - size) // step
    if nfr < 10:
        return np.zeros(int(len(a) / sr / hop))
    win = np.hanning(size).astype(np.float32)
    lo, hi = int(1000 * size / sr), int(6000 * size / sr)
    flux, prev = np.zeros(nfr, dtype=np.float32), None
    for c0 in range(0, nfr, 8000):                                   # по частям — длинный стрим не займёт всю память
        idx = np.arange(c0, min(nfr, c0 + 8000))[:, None] * step + np.arange(size)[None, :]
        mag = np.abs(np.fft.rfft(a[idx] * win, axis=1))[:, lo:hi]
        mag = np.log1p(mag * 10)
        base = np.vstack([prev[None, :] if prev is not None else mag[:1], mag[:-1]])
        flux[c0:c0 + len(mag)] = np.clip(mag - base, 0, None).sum(axis=1)
        prev = mag[-1]
    thr = np.median(flux) + 3 * np.median(np.abs(flux - np.median(flux)))
    hits = (flux > thr) & (flux >= np.roll(flux, 1)) & (flux >= np.roll(flux, -1))
    per = int(hop * sr / step)
    n = nfr // per
    dens = hits[:n * per].reshape(n, per).sum(axis=1).astype(float)
    k = int(2.0 / hop)
    return np.convolve(dens, np.ones(k) / k, mode="same")


def cut_curve(cuts, n, hop=HOP):
    """Частота смены кадров (за 8 с): так выглядят сценки — диалоги и катсцены, где камера переключается на героев."""
    out = np.zeros(n)
    for t in cuts:
        i = int(t / hop)
        if 0 <= i < n:
            out[i] += 1
    k = int(8 / hop)
    return np.convolve(out, np.ones(k), mode="same")


def score_curve(audio, motion, speech, onsets=None, cuts=None):
    """Оценка «насколько интересно» по шагам: звук боя (резкие удары), всплеск громкости над фоном, движение,
    эмоции в речи, частые смены кадров (сценки)."""
    parts = [audio, motion, speech] + [x for x in (onsets, cuts) if x is not None]
    n = max(len(x) for x in parts)
    pad = lambda x: np.pad(np.asarray(x, dtype=float), (0, n - len(x))) if x is not None else np.zeros(n)   # noqa: E731
    a, m, s, o, c = pad(audio), pad(motion), pad(speech), pad(onsets), pad(cuts)
    k = int(8 / HOP) | 1                                            # «фон» звука — медиана за 8 с
    bg = np.array([np.median(a[max(0, i - k // 2):i + k // 2 + 1]) for i in range(0, n)]) if n < 200000 else a
    burst = np.clip(a - bg, 0, None)
    if onsets is None and cuts is None:                             # старый набор сигналов
        sc = 0.45 * _norm(burst) + 0.2 * _norm(m) + 0.35 * _norm(s)
    else:
        sc = 0.3 * _norm(o) + 0.2 * _norm(burst) + 0.15 * _norm(m) + 0.2 * _norm(s) + 0.15 * _norm(c)
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


# --- ИИ выбирает моменты: смотрит кадры и читает речь ---
def candidates(score, words, secs, n=12, length=30.0):
    """Кандидаты для ИИ: лучшие пики оценки и равномерно по всей записи (ИИ должен увидеть и тихие сценки-диалоги,
    которые сигналы не замечают). Не пересекаются. [(начало, конец, пик, оценка)]."""
    lo, hi = LENGTH
    length = min(hi, max(lo, float(length)))
    peaks = pick_moments(score, words, secs, max(2, n // 2), length)
    out = list(peaks)
    k = max(1, int(secs // length))
    for j in range(k):                                                # равномерно: середины отрезков длиной length
        a = j * secs / k
        b = min(secs, a + length)
        if b - a < lo * 0.8 or any(not (b <= x or a >= y) for x, y, _p, _s in out):
            continue
        sc = float(np.max(score[int(a / HOP):int(b / HOP)])) if len(score) else 0.0
        out.append((round(a, 2), round(b, 2), round(a + (b - a) / 2, 2), round(sc, 3)))
    even = out[len(peaks):]
    room = max(0, n - len(peaks))
    if len(even) > room:                                              # равномерные — через равные промежутки, не по оценке
        even = [even[round(i * (len(even) - 1) / max(1, room - 1))] for i in range(room)] if room else []
    return sorted({m[0]: m for m in peaks + even}.values(), key=lambda m: m[0])


def frames_jpeg(video, times, width=448):
    """Кадры записи в моменты times — JPEG (байты) для ИИ."""
    from . import studio

    out = []
    for t in times:
        r = subprocess.run([studio.ffmpeg(), "-v", "error", "-ss", "{:.2f}".format(t), "-i", str(video), "-frames:v", "1",
                            "-vf", "scale={}:-2".format(width), "-q:v", "6", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                           capture_output=True, timeout=60)
        if r.stdout:
            out.append(r.stdout)
    return out


JUDGE = """Ты — редактор YouTube Shorts по играм{game}. Ниже кандидаты — отрезки записи: у каждого 3 кадра (начало, середина,
конец) и речь в нём. Оцени каждый как будущий Short от 0 до 10.
ХОРОШО (высокий балл): смешное и нелепое (неудачи, абсурд, смешные реплики, странные монстры и NPC), эффектный бой
(магия, взрывы, погони, красивые добивания), монстры, сильные моменты истории персонажа, яркий или крутой диалог,
неожиданный поворот, эмоции стримера.
ПЛОХО (низкий балл): просто езда или прогулка по миру, меню, карта, загрузка, инвентарь, спокойные пояснения поверх
обычной ходьбы, тёмные кадры, где ничего не видно.
Для каждого ответь: "i" (номер), "score" (0–10), "kind" (бой | смешно | монстр | история | диалог | пейзаж | скучно),
"why" (одна фраза по-русски), "hook" (надпись на первые 2 секунды, до 5 слов, по-русски, правда о моменте),
"title" (название Short по-русски до 70 знаков, без обмана).
И один раз для всей записи — "style": какой стиль надписей подходит атмосфере игры: {styles}.
Ответь ТОЛЬКО JSON: {{"style": "…", "clips": [{{"i": 1, "score": 0, "kind": "", "why": "", "hook": "", "title": ""}}, …]}}"""


def ask_vision(prompt, images):
    """Модель с «глазами» (Claude): картинки + текст → ответ. Нет ключа Anthropic — ClipperError."""
    import base64

    from . import config

    if not config.ANTHROPIC_KEY:
        raise ClipperError("нет ключа Claude — ИИ-отбор недоступен")
    import anthropic

    content = []
    for label, img in images:
        if label:
            content.append({"type": "text", "text": label})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.standard_b64encode(img).decode()}})
    content.append({"type": "text", "text": prompt})
    r = anthropic.Anthropic(timeout=300, max_retries=1).messages.create(
        model=config.MIXED_STRONG or "claude-haiku-5-5", max_tokens=4000, messages=[{"role": "user", "content": content}])
    return "".join(b.text for b in r.content if b.type == "text")


def judge(video, cands, words, game="", vision=None, batch=12):  # noqa: C901
    """ИИ оценивает кандидатов по кадрам и речи. Возвращает [{"i", "score", "kind", "why", "hook", "title"}] по
    порядку cands; модель недоступна — None (тогда выбор по сигналам). Стиль надписей, который ИИ счёл подходящим
    атмосфере игры, — в judge.style."""
    vision = vision or ask_vision
    out = [None] * len(cands)
    judge.style = None
    for b0 in range(0, len(cands), batch):
        part = cands[b0:b0 + batch]
        images = []
        lines = []
        for j, (a, b, _p, _s) in enumerate(part, 1):
            shots = frames_jpeg(video, [a + (b - a) * x for x in (0.15, 0.5, 0.85)])
            for k, img in enumerate(shots):
                images.append(("Кандидат {} ({}–{}), кадр {}:".format(j, _ts(a), _ts(b), k + 1), img))
            speech = " ".join(w["w"] for w in words if a <= w["s"] < b)[:500]
            lines.append("{}. {}–{}: речь: {}".format(j, _ts(a), _ts(b), speech or "(без слов)"))
        prompt = JUDGE.format(game=" ({})".format(game) if game else "",
                              styles=", ".join("{} — {}".format(k, v["name"]) for k, v in STYLES.items())) + \
            "\n\nКАНДИДАТЫ:\n" + "\n".join(lines)
        try:
            reply = vision(prompt, images)
            m = re.search(r"\{.*\}", reply or "", re.S)
            data = json.loads(m.group(0)) if m else {}
            got = data.get("clips", [])
            if data.get("style") in STYLES and not judge.style:
                judge.style = data["style"]
        except Exception as e:                                         # noqa: BLE001 — без ИИ — по сигналам
            print("[нарезчик: ИИ-отбор — {}]".format(str(e)[:120]))
            return None
        for g in got:
            try:
                j = int(g.get("i")) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= j < len(part):
                out[b0 + j] = {"score": float(g.get("score") or 0), "kind": str(g.get("kind") or ""),
                               "why": str(g.get("why") or ""), "hook": str(g.get("hook") or "").strip(),
                               "title": str(g.get("title") or "").strip()[:90]}
    return out


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


# --- стили под атмосферу игры ---
FONT_FILES = {"Alegreya SC": "alegreyasc/AlegreyaSC-Black.ttf", "Ruslan Display": "ruslandisplay/RuslanDisplay-Regular.ttf",
              "Rubik Mono One": "rubikmonoone/RubikMonoOne-Regular.ttf", "Russo One": "russoone/RussoOne-Regular.ttf",
              "Rubik Glitch": "rubikglitch/RubikGlitch-Regular.ttf", "Rubik Wet Paint": "rubikwetpaint/RubikWetPaint-Regular.ttf",
              "Press Start 2P": "pressstart2p/PressStart2P-Regular.ttf", "Stalinist One": "stalinistone/StalinistOne-Regular.ttf"}
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/"     # Google Fonts, лицензия OFL, с кириллицей
STYLES = {
    "classic": {"name": "Классика", "caption": ("Noto Sans", True), "hook": ("Noto Sans", True), "fill": (1, 1, 1),
                "stroke": (0.04, 0.04, 0.06), "accent": (1.0, 0.84, 0.0), "hook_color": (1, 1, 1), "glow": None, "size": 1.0},
    "fantasy": {"name": "Фэнтези (Ведьмак, Skyrim, Elden Ring)", "caption": ("Alegreya SC", False),
                "hook": ("Ruslan Display", False), "fill": (1.0, 0.95, 0.84), "stroke": (0.16, 0.08, 0.03),
                "accent": (1.0, 0.76, 0.28), "hook_color": (1.0, 0.82, 0.42), "glow": None, "size": 1.05},
    "vice": {"name": "Vice / Майами (GTA, Saints Row)", "caption": ("Rubik Mono One", False), "hook": ("Rubik Mono One", False),
             "fill": (1, 1, 1), "stroke": (0.2, 0.02, 0.28), "accent": (1.0, 0.25, 0.62), "hook_color": (0.25, 0.95, 1.0),
             "glow": (1.0, 0.25, 0.62), "size": 0.82},
    "cyber": {"name": "Киберпанк (Cyberpunk 2077, Deus Ex)", "caption": ("Russo One", False), "hook": ("Rubik Glitch", False),
              "fill": (0.99, 0.93, 0.04), "stroke": (0.02, 0.02, 0.03), "accent": (0.0, 0.94, 1.0),
              "hook_color": (0.99, 0.93, 0.04), "glow": (0.0, 0.94, 1.0), "size": 0.95},
    "military": {"name": "Военный (CoD, Battlefield, CS, PUBG)", "caption": ("Russo One", False), "hook": ("Stalinist One", False),
                 "fill": (1, 1, 1), "stroke": (0.1, 0.12, 0.06), "accent": (1.0, 0.55, 0.1), "hook_color": (1.0, 0.6, 0.15),
                 "glow": None, "size": 0.9},
    "horror": {"name": "Хоррор (Resident Evil, Silent Hill)", "caption": ("Russo One", False), "hook": ("Rubik Wet Paint", False),
               "fill": (0.95, 0.95, 0.95), "stroke": (0.0, 0.0, 0.0), "accent": (0.9, 0.06, 0.06),
               "hook_color": (0.9, 0.06, 0.06), "glow": None, "size": 0.95},
    "pixel": {"name": "Пиксель (Minecraft, Terraria, Roblox)", "caption": ("Press Start 2P", False),
              "hook": ("Press Start 2P", False), "fill": (1, 1, 1), "stroke": (0.05, 0.05, 0.05), "accent": (0.35, 1.0, 0.35),
              "hook_color": (0.35, 1.0, 0.35), "glow": None, "size": 0.62},
}
GAME_STYLE = ((("witcher", "ведьмак", "skyrim", "elden", "dragon age", "baldur", "diablo", "dark souls", "lord of the rings",
                "kingdom come", "fantasy"), "fantasy"),
              (("gta", "grand theft", "vice city", "saints row", "гта"), "vice"),
              (("cyberpunk", "киберпанк", "2077", "deus ex", "ghostrunner"), "cyber"),
              (("call of duty", "cod ", "battlefield", "counter", "cs2", "cs:go", "pubg", "warzone", "tarkov", "arma"), "military"),
              (("resident evil", "silent hill", "outlast", "dead by daylight", "alan wake", "horror", "хоррор"), "horror"),
              (("minecraft", "майнкрафт", "terraria", "roblox", "stardew"), "pixel"))


def style_for(game):
    """Стиль по названию игры (Ведьмак — фэнтези, GTA — Vice, Cyberpunk — киберпанк…); незнакомая — None."""
    low = " {} ".format(game or "").lower()
    return next((st for keys, st in GAME_STYLE if any(k in low for k in keys)), None)


def ensure_fonts():
    """Шрифты стилей — в ~/.local/share/fonts/chloe (только для пользователя), один раз; нет сети — классический шрифт."""
    import urllib.request

    folder = pathlib.Path.home() / ".local" / "share" / "fonts" / "chloe"
    missing = [f for f in FONT_FILES.values() if not (folder / pathlib.Path(f).name).exists()]
    if not missing:
        return True
    folder.mkdir(parents=True, exist_ok=True)
    for f in missing:
        try:
            with urllib.request.urlopen(FONT_URL + f, timeout=60) as r:
                (folder / pathlib.Path(f).name).write_bytes(r.read())
        except OSError:
            return False
    subprocess.run(["fc-cache", "-f", str(folder)], capture_output=True)
    return True


def _set_font(c, family, bold, size):
    c.select_font_face(family, 0, 1 if bold else 0)
    c.set_font_size(size)


def _paint_word(c, text, size, fill, style, alpha=1.0):
    """Слово по текущему пути: свечение (неоновые стили), толстая обводка, заливка."""
    c.text_path(text)
    if style.get("glow"):
        for wdt, al in ((size * 0.5, 0.18), (size * 0.32, 0.3)):
            c.set_source_rgba(*style["glow"], al * alpha)
            c.set_line_width(wdt)
            c.set_line_join(1)
            c.stroke_preserve()
    c.set_source_rgba(*style["stroke"], alpha)
    c.set_line_width(size * 0.2)
    c.set_line_join(1)
    c.stroke_preserve()
    c.set_source_rgba(*fill, alpha)
    c.fill()


def draw_caption(c, group, t, y, style=None):
    """Субтитр в стиле игры: слова группы крупно, текущее — цветом стиля и чуть крупнее (подпрыгивает)."""
    st = STYLES.get(style) if isinstance(style, str) else (style or STYLES["classic"])
    st = st or STYLES["classic"]
    _s, _e, ws = group
    family, bold = st["caption"]
    size = 82 * st["size"]
    _set_font(c, family, bold, size)
    full = c.text_extents(" ".join(w["w"].upper() for w in ws)).x_advance * 1.1
    if full * 1.12 > SH.SIZE[0] * SH.SAFE_W:                             # не влезает — шрифт меньше (с запасом на «прыжок»)
        size = size * SH.SIZE[0] * SH.SAFE_W / (full * 1.12)
        _set_font(c, family, bold, size)
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
        _paint_word(c, w["w"].upper(), size, st["accent"] if now else st["fill"], st)
        c.restore()
        x += wd + space


def draw_hook(c, text, y, style=None, alpha=1.0, scale=1.0):
    """Крючок в стиле игры: крупно по центру, в 1–2 строки, одно слово — акцентным цветом."""
    st = STYLES.get(style) if isinstance(style, str) else (style or STYLES["classic"])
    st = st or STYLES["classic"]
    family, bold = st["hook"]
    size = 104 * st["size"] * scale
    _set_font(c, family, bold, size)
    words = text.split()
    acc = SH.accent_word(text)
    lines, cur = [], []
    for w in words:                                                   # перенос по ширине; предлог — к следующему слову
        if cur and c.text_extents(" ".join(cur + [w])).x_advance > SH.SIZE[0] * SH.SAFE_W:
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    for i in range(len(lines) - 1):
        if len(lines[i]) > 1 and len(lines[i][-1]) <= 2:
            lines[i + 1].insert(0, lines[i].pop())
    sp = c.text_extents(" ").x_advance * 1.2
    for n, line in enumerate(lines):
        ws = [c.text_extents(w).x_advance for w in line]
        x = (SH.SIZE[0] - (sum(ws) + sp * (len(line) - 1))) / 2
        yy = y + size + n * size * 1.18
        for w, wd in zip(line, ws):
            c.move_to(x, yy)
            col = st["accent"] if acc and w.strip(".,!?…«»").lower() == acc.lower() else st["hook_color"]
            _paint_word(c, w, size, col, st, alpha)
            x += wd + sp


def render_clip(video, out, a, b, peak, layout, cam, words, hook, info, progress=None, style=None):
    """Один клип → mp4 1080×1920: кадры через cairo, звук — тот же отрезок с плавными краями и громкостью −14 LUFS."""
    import cairo

    from . import studio

    W = 1920
    H = int(round(info["h"] * W / info["w"] / 2) * 2)
    OW, OH = SH.SIZE
    dur = b - a
    groups = caption_groups(words, a, b)
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
                draw_hook(c, hook, max(SAFE_TOP, OH * (0.04 if layout == "streamer" else 0.12)), style, alpha, 0.85 + 0.15 * min(1.0, tt / 0.12))
            g = next((g for g in groups if g[0] <= t < g[1]), None)
            if g:
                y = OH * CAM_H + 110 if layout == "streamer" else min(OH * 0.68, bottom + 120)
                draw_caption(c, g, t, y, style)
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


def foreign(words, a, b, target="ru"):
    """Речь в клипе не на языке канала? (по буквам: для русского канала — латиница вместо кириллицы)."""
    text = "".join(w["w"] for w in words if a <= w["s"] < b)
    lat = len(re.findall(r"[A-Za-z]", text))
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))
    if target == "ru":
        return lat > 20 and lat > cyr * 2
    return cyr > 20 and cyr > lat * 2


TRANSLATE = """Переведи субтитры игрового ролика на {lang}. Живо и коротко, как говорят игроки, без лишних слов; имена
персонажей — как в русской локализации игры{game}. Каждая строка — отдельная фраза: переводи её отдельно, НЕ склеивай
строки и не дели их (даже если строка — обрывок предложения). Ответь ТОЛЬКО JSON — перевод под номером каждой
строки: {{"lines": {{"1": "…", "2": "…", …}}}} — все {n} номеров.

СТРОКИ:
{lines}"""


def sentences(words, a, b):
    """Слова клипа по предложениям (точка, ?, ! или пауза больше 0,8 с): [(начало, конец, [слова])]."""
    out, cur = [], []
    for w in (w for w in words if a <= w["s"] < b and w["w"]):
        if cur and w["s"] - cur[-1]["e"] > 0.8:
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", w["w"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [(g[0]["s"], g[-1]["e"], g) for g in out]


def translate_words(words, a, b, game="", ask=None, target="ru"):
    """Речь клипа → переведённые «слова» с временем: фразы переводятся целиком, слова перевода раскладываются
    по времени фразы поровну (подсветка идёт в том же темпе). Не вышло — исходные слова."""
    groups = sentences(words, a, b)
    if not groups:
        return words
    if ask is None:
        try:
            from .screenplay import model_ask as ask
        except ImportError:
            return words
    texts = [" ".join(w["w"] for w in g[2]) for g in groups]
    prompt = TRANSLATE.format(lang={"ru": "русский"}.get(target, target), game=" " + game if game else "", n=len(texts),
                              lines="\n".join("{}. {}".format(i + 1, t) for i, t in enumerate(texts)))
    try:
        try:
            reply = ask(prompt, False)
        except TypeError:
            reply = ask(prompt)
        m = re.search(r"\{.*\}", reply or "", re.S)
        lines = json.loads(m.group(0)).get("lines") if m else None
    except Exception as e:                                             # noqa: BLE001 — без перевода — как есть
        print("[нарезчик: перевод — {}]".format(str(e)[:80]))
        return words
    if isinstance(lines, list) and len(lines) == len(groups):          # старый формат — списком
        lines = {str(i + 1): t for i, t in enumerate(lines)}
    if not isinstance(lines, dict) or not lines:
        return words
    lines = [lines.get(str(i + 1)) or " ".join(w["w"] for w in g[2]) for i, g in enumerate(groups)]   # нет перевода — как было
    out = [w for w in words if not (a <= w["s"] < b)]
    for (s0, e0, _ws), line in zip(groups, lines):
        tw = str(line).split()
        if not tw:
            continue
        step = (e0 - s0) / len(tw)
        out += [{"s": round(s0 + k * step, 2), "e": round(s0 + (k + 1) * step - 0.02, 2), "w": t} for k, t in enumerate(tw)]
    return sorted(out, key=lambda w: w["s"])


def choose_moments(video, score, words, secs, count, length, game="", vision=None):
    """Какие моменты резать: ИИ смотрит кадры и читает речь кандидатов (см. judge) и выбирает лучшие (балл ≥ 4);
    ИИ недоступен — лучшие пики сигналов. Возвращает (моменты, данные ИИ или None)."""
    cands = candidates(score, words, secs, max(12, count * 3), length) if vision is not False else []
    res = judge(video, cands, words, game, vision or None) if cands else None
    if not res:
        return pick_moments(score, words, secs, count, length), None
    ranked = sorted(((r["score"], c, r) for c, r in zip(cands, res) if r and r["score"] >= 4), key=lambda x: -x[0])
    chosen = [(c[0], c[1], c[2], round(sc / 10, 3)) for sc, c, _r in ranked[:count]]
    meta = [r for _sc, _c, r in ranked[:count]]
    if not chosen:
        return pick_moments(score, words, secs, count, length), None
    return chosen, meta


def clip(video, out_dir=None, count=5, length=30.0, game="", layout="auto", lang=None, ask=None, progress=print,
         vision=None, translate=True, style=None):
    """Запись → лучшие моменты (ИИ смотрит кадры кандидатов; vision=False — только сигналы) → Shorts в out_dir (по умолчанию — рядом с записью, папка «<имя>-shorts») + clips.txt.
    Возвращает [(путь, начало, конец, оценка, название)]."""
    video = pathlib.Path(video)
    info = probe(video)
    out_dir = pathlib.Path(out_dir or video.with_name(video.stem + "-shorts"))
    out_dir.mkdir(parents=True, exist_ok=True)
    progress("Слушаю и смотрю запись ({:.0f} мин)…".format(info["secs"] / 60))
    audio = audio_curve(video) if info["audio"] else np.zeros(int(info["secs"] / HOP))
    motion, cuts = motion_curve(video)
    onsets = onset_curve(video) if info["audio"] else None
    words = transcribe(video, out_dir / "речь.json", lang) if info["audio"] else []
    n = max(len(audio), len(motion))
    score = score_curve(audio, motion, speech_curve(words, n), onsets, cut_curve(cuts, n))
    judge.style = None
    moments, meta = choose_moments(video, score, words, info["secs"], count, length, game, vision)
    style = style if style in STYLES else (style_for(game) or judge.style or "classic")
    if style != "classic" and not ensure_fonts():
        style = "classic"
    progress("Стиль надписей: {}".format(STYLES[style]["name"]))
    if not moments:
        raise ClipperError("не нашлось моментов (запись слишком короткая?)")
    if not meta:                                                       # без ИИ — крючки и названия по речи
        meta = clip_meta([" ".join(w["w"] for w in words if a <= w["s"] < b) for a, b, _p, _s in moments], game, ask)
    cam = find_facecam(video, info["secs"]) if layout in ("auto", "streamer") else None
    lay = "streamer" if cam else "game"
    made = []
    for i, ((a, b, peak, sc), m) in enumerate(zip(moments, meta), 1):
        out = out_dir / "clip-{:02d}.mp4".format(i)
        progress("Клип {} из {}: {:.0f}–{:.0f} с{}".format(i, len(moments), a, b, " — " + m["why"] if m.get("why") else ""))
        cw = translate_words(words, a, b, game, ask) if (translate and foreign(words, a, b)) else words
        render_clip(video, out, a, b, peak, lay, cam, cw, m["hook"], info, style=style)
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
