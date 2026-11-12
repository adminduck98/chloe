"""Shorts: из готового ролика 16:9 — вертикальные куски 9:16 (1080×1920) с крючком в первые 2 секунды.

Что делает:
  • выбирает куски: целые сцены подряд, 15–58 с, где больше всего движения и звука (несколько роликов — не пересекаются);
  • «оператор»: вертикальная рамка следит за героями (мультфильм — точные положения из мультипликатора, с учётом
    камеры сцены); герои разошлись шире рамки — камера плавно отъезжает, сверху и снизу — размытый тот же кадр;
    слайды и живое видео — весь кадр по ширине на размытом фоне;
  • крючок: крупная надпись в первые 2,5 с; если начало куска спокойное — сначала 1,2 с самого яркого момента
    этого же куска (вспышка — и история с начала);
  • субтитры — заново, крупно и в безопасной зоне Shorts (снизу экран закрыт названием и кнопками); вшитые
    в ролик субтитры остаются за рамкой;
  • файл shorts.txt: название с #Shorts, описание, что связать с полным роликом.

Всё считается на этом компьютере, без оплаты.
"""
import json
import math
import pathlib
import subprocess

import numpy as np

SIZE = (1080, 1920)
MIN_SECS, MAX_SECS = 15.0, 58.0          # YouTube принимает Shorts до 3 минут, но короткие досматривают — до минуты
HOOK_SECS = 2.5                          # сколько держится надпись-крючок
TEASER = 1.2                             # «самый яркий момент» в начале, если начало спокойное
FLASH = 0.12                             # вспышка на стыке тизера и начала
CAP_Y, HOOK_Y = 0.64, 0.15               # субтитры и крючок — доли высоты (низ экрана Shorts закрыт подписями)
SAFE_W = 0.78                            # ширина текста: справа кнопки Shorts
TRACK = (384, 216)                       # размер, в котором мультипликатор пересчитывает положения героев
ACCENT = (1.0, 0.84, 0.0)


class ShortsError(Exception):
    pass


# --- где сцены, где движение ---
def scene_spans(folder, count):
    """Начало и конец каждой сцены в готовом ролике (клипы склеены встык): [(начало, конец)]."""
    from . import studio

    out, at = [], 0.0
    for i in range(count):
        clip = pathlib.Path(folder) / "clip{:02d}.mp4".format(i)
        if not clip.exists():
            break
        d = studio.duration(clip)
        out.append((at, at + d))
        at += d
    return out


def audio_level(video, fps=25):
    """Громкость звука по кадрам (среднеквадратичная, 0..1)."""
    from . import studio

    sr = 8000
    r = subprocess.run([studio.ffmpeg(), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True, timeout=300)
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768
    hop = sr // fps
    n = len(a) // hop
    if n == 0:
        return np.zeros(0)
    return np.sqrt(np.mean(a[:n * hop].reshape(n, hop) ** 2, axis=1))


def energy(video, fps=25):
    """«Насколько интересно» по кадрам: движение картинки + громкость (каждое — к своему 95-му процентилю)."""
    from . import studio

    m, a = studio.video_motion(video, fps), audio_level(video, fps)
    n = max(len(m), len(a))
    if n == 0:
        return np.zeros(0)

    def norm(x):
        x = np.pad(x, (0, n - len(x)))
        p = np.percentile(x, 95) if len(x) else 0
        return np.clip(x / p, 0, 1.5) if p > 0 else x
    return 0.6 * norm(m) + 0.4 * norm(a)


def candidates(spans, en, fps=25):
    """Куски-кандидаты: сцены подряд от MIN_SECS до MAX_SECS; одна длинная сцена — лучшее окно внутри неё.
    [(начало, конец, оценка)]."""
    def score(a, b):
        seg = en[int(a * fps):int(b * fps)]
        return float(seg.mean() + 0.3 * np.percentile(seg, 90)) if len(seg) else 0.0

    total = spans[-1][1] if spans else 0.0
    out = []
    if total <= MAX_SECS:                                          # весь ролик помещается — это и есть история целиком
        out.append((0.0, total, score(0.0, total) * 1.1))
    for i, (s, _e) in enumerate(spans):
        for j in range(i, len(spans)):
            a, b = s, spans[j][1]
            d = b - a
            if d > MAX_SECS:
                if j == i:                                         # одна сцена длиннее минуты — окно внутри
                    best = max(((score(x, x + MAX_SECS), x) for x in np.arange(a, b - MAX_SECS + 0.01, 2.0)), default=None)
                    if best:
                        out.append((float(best[1]), float(best[1]) + MAX_SECS, best[0]))
                break
            if d >= MIN_SECS and not (a == 0.0 and b == total):
                out.append((a, b, score(a, b) * (1.0 if 20 <= d <= 50 else 0.88)))
    if not out and total > 0:                                      # ролик короче 15 с — весь
        out.append((0.0, total, score(0.0, total)))
    return out


def choose(cands, count):
    """Лучшие куски, которые не пересекаются; по порядку в ролике."""
    chosen = []
    for a, b, sc in sorted(cands, key=lambda c: -c[2]):
        if all(b <= x or a >= y for x, y, _ in chosen):
            chosen.append((a, b, sc))
        if len(chosen) == count:
            break
    return sorted(chosen)


def default_count(total):
    return max(1, min(3, int(round(total / 35.0))))


def teaser_at(en, a, b, fps=25, seen=None):
    """Начало куска спокойное → откуда взять тизер (самое яркое место куска после 3-й секунды, где герой виден —
    seen(время) → да/нет); иначе None."""
    seg = en[int(a * fps):int(b * fps)].copy()
    if seen is not None:
        seg = seg * np.array([1.0 if seen(a + k / fps) else 0.0 for k in range(len(seg))])
    if len(seg) < (3 + TEASER) * fps:
        return None
    head = seg[:2 * fps].mean()
    if head >= 0.7 * np.percentile(seg, 95):
        return None
    if seen is not None:
        seg = np.where(seg > 0, seg, -5.0)                         # окно, где героя нет хоть на кадр, — не годится
    k = int(TEASER * fps)
    sums = np.convolve(seg, np.ones(k), mode="valid")
    lo = 3 * fps
    i = lo + int(np.argmax(sums[lo:]))
    return a + i / fps


# --- оператор ---
def caption_band(look, has_words):
    """Какая полоса кадра свободна от вшитых субтитров: (верх, низ) в долях высоты."""
    if not has_words:
        return 0.0, 1.0
    return (0.13, 1.0) if look == "neon_desktop" else (0.0, 0.83)


def track_anim(spec, look, secs, words=None, size=TRACK):
    """Мультфильм: где герои на каждом кадре сцены — рамка всех видимых героев (доли кадра) или None.
    Сцена пересчитывается тем же мультипликатором (пружины суставов идут кадр за кадром, как в ролике)."""
    import cairo

    from . import animator

    w, h = size
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    c = cairo.Context(surf)
    scene = animator.Scene(spec, look, size, secs, None, words)
    seen = {}
    orig = scene._actor

    def spy(cc, aid, t, ink, measure=False):
        res = orig(cc, aid, t, ink, measure=measure)
        if measure and cc is not None:
            _hand, pts, r = res
            dev = [cc.user_to_device(x, y) for x, y in pts.values()]
            rr = abs(cc.user_to_device_distance(r, 0)[0])
            seen[aid] = (min(p[0] for p in dev) - rr, min(p[1] for p in dev) - rr, max(p[0] for p in dev) + rr, max(p[1] for p in dev) + rr)
        return res
    scene._actor = spy
    game = spec.get("game") or {}
    play = game.get("play")                                        # кнопка Play — цель героя (на экране выбора и в уровне)
    out = []
    for i in range(int(round(secs * animator.FPS))):
        seen.clear()
        scene.render(c, scene.scene_time(i / animator.FPS), cairo)
        if play and seen:
            ts = scene.scene_time(i / animator.FPS)
            off = scene.scroll(ts) * w if game.get("world") == "level" else 0.0
            px, py, pr = float(play.get("x", 0.8)) * w - off, float(play.get("y", 0.6)) * h, h * 0.16
            if -pr < px < w + pr:                                  # в уровне — только когда кнопка уже на экране
                seen["_play"] = (px - pr, py - pr, px + pr, py + pr)
        if seen:
            x0, y0 = min(b[0] for b in seen.values()), min(b[1] for b in seen.values())
            x1, y1 = max(b[2] for b in seen.values()), max(b[3] for b in seen.values())
            out.append((max(0.0, x0 / w), max(0.0, y0 / h), min(1.0, x1 / w), min(1.0, y1 / h)))
        else:
            out.append(None)
    return out


def _smooth(x, sigma):
    """Сгладить без запаздывания (ролик готов — можно смотреть вперёд): гауссово окно, края — ближайшим значением."""
    if sigma <= 0 or len(x) < 3:
        return np.asarray(x, dtype=float)
    k = int(sigma * 3)
    g = np.exp(-0.5 * (np.arange(-k, k + 1) / sigma) ** 2)
    g /= g.sum()
    pad = np.pad(np.asarray(x, dtype=float), k, mode="edge")
    return np.convolve(pad, g, mode="valid")


def camera(boxes, band, frame=(1920, 1080), fps=25):
    """Рамки героев по кадрам → оператор: (центр x, ширина рамки) в пикселях кадра на каждом кадре.
    Ширина — не уже вертикальной рамки во всю высоту полосы и не шире кадра; нет героев — весь кадр."""
    W, H = frame
    ch = (band[1] - band[0]) * H
    narrow = ch * 9 / 16
    cx, cw = [], []
    last = (W / 2, W)
    for b in boxes:
        if b is None:
            cx.append(last[0] if last[1] < W else W / 2)
            cw.append(W if last[1] >= W else last[1])
            continue
        bw = (b[2] - b[0]) * W
        want = min(W, max(narrow, bw * 1.35 + W * 0.04))
        last = ((b[0] + b[2]) / 2 * W, want)
        cx.append(last[0])
        cw.append(want)
    if not cx:
        return []
    cw = _smooth(cw, 0.6 * fps)
    cw = np.maximum.reduce([cw, np.full(len(cw), narrow)])
    cx = _smooth(cx, 0.35 * fps)
    cx = np.clip(cx, cw / 2, W - cw / 2)
    return [(float(a), float(b)) for a, b in zip(cx, cw)]


# --- текст ---
def _font(c, size):
    c.select_font_face("Noto Sans", 0, 1)
    c.set_font_size(size)


def wrap_words(c, words, max_w):
    lines, cur = [], []
    for wd in words:
        test = " ".join(cur + [wd])
        if cur and c.text_extents(test).x_advance > max_w:
            lines.append(cur)
            cur = [wd]
        else:
            cur.append(wd)
    if cur:
        lines.append(cur)
    for i in range(len(lines) - 1):                                # предлог не остаётся один в конце строки
        if len(lines[i]) > 1 and len(lines[i][-1]) <= 2:
            lines[i + 1].insert(0, lines[i].pop())
    return lines


def draw_text(c, text, y, size, accent=None, alpha=1.0, scale=1.0):
    """Крупный текст по центру: белый с толстой тёмной обводкой, слово accent — жёлтым. y — верх первой строки."""
    W = SIZE[0]
    _font(c, size * scale)
    lines = wrap_words(c, text.split(), W * SAFE_W)
    lh = size * scale * 1.18
    for n, line in enumerate(lines):
        full = " ".join(line)
        x = (W - c.text_extents(full).x_advance) / 2
        yy = y + size * scale + n * lh
        sp = c.text_extents(" ").x_advance
        for wd in line:
            c.move_to(x, yy)
            c.text_path(wd)
            c.set_source_rgba(0.05, 0.05, 0.08, alpha)
            c.set_line_width(size * scale * 0.18)
            c.set_line_join(1)
            c.stroke_preserve()
            col = ACCENT if accent and wd.strip(".,!?…«»").lower() == accent.lower() else (1, 1, 1)
            c.set_source_rgba(*col, alpha)
            c.fill()
            x += c.text_extents(wd).x_advance + sp
    return len(lines) * lh


def accent_word(text):
    """Какое слово крючка выделить цветом: самое длинное (обычно главное)."""
    words = [w.strip(".,!?…«»") for w in text.split()]
    return max(words, key=len) if words else None


HOOKS = """Ты делаешь YouTube Shorts из мультфильма. Для каждого куска придумай надпись-крючок на первые 2 секунды:
до 5 слов, по-русски, интрига или вопрос, только то, что правда есть в куске (без обмана).
Ответь ТОЛЬКО JSON: {{"hooks": ["…", …]}} — ровно {n} строк, по порядку кусков.

РОЛИК: {title} — {logline}
КУСКИ:
{parts}"""


def hook_texts(script, parts, ask=None):
    """Надписи-крючки для каждого куска: от модели; нет модели — из сценария (обложка, второй вариант, название)."""
    base = [t for t in (script.get("cover"), script.get("cover_alt"), script.get("title")) if t] or ["Смотри до конца"]
    fallback = [base[i % len(base)] for i in range(len(parts))]
    if ask is False:
        return fallback
    if ask is None:
        try:
            from .screenplay import model_ask as ask
        except ImportError:
            return fallback
    text = HOOKS.format(n=len(parts), title=script.get("title", ""), logline=script.get("logline", ""),
                        parts="\n".join("{}. {}".format(i + 1, p) for i, p in enumerate(parts)))
    try:
        try:
            reply = ask(text, False)
        except TypeError:
            reply = ask(text)
        import re

        m = re.search(r"\{.*\}", reply or "", re.S)
        hooks = [str(h).strip() for h in (json.loads(m.group(0)).get("hooks") or [])] if m else []
    except Exception as e:                                         # noqa: BLE001 — без модели берём из сценария
        print("[shorts: модель — {}]".format(str(e)[:80]))
        hooks = []
    return [h if h and len(h.split()) <= 7 else fb for h, fb in zip(hooks + [""] * len(parts), fallback)]


# --- кадр Shorts ---
def compose(c, src, cam, band, frame, cairo):
    """Один кадр 1080×1920 из кадра ролика: рамка оператора; рамка шире вертикали — сверху и снизу размытый фон."""
    W, H = frame
    OW, OH = SIZE
    cx, cw = cam
    y0, y1 = band[0] * H, band[1] * H
    ch = y1 - y0
    x0 = min(max(0.0, cx - cw / 2), W - cw)
    s = OW / cw
    dh = ch * s
    c.identity_matrix()
    if dh < OH - 1:                                                # фон: тот же кадр, крупно и размыто, притемнён
        bg_w = ch * OW / OH
        bx = min(max(0.0, cx - bg_w / 2), W - bg_w)
        small = cairo.ImageSurface(cairo.FORMAT_RGB24, 18, 32)
        sc = cairo.Context(small)
        sc.scale(18 / bg_w, 32 / ch)
        sc.translate(-bx, -y0)
        sc.set_source_surface(src, 0, 0)
        sc.paint()
        c.save()
        c.scale(OW / 18, OH / 32)
        c.set_source_surface(small, 0, 0)
        c.get_source().set_filter(cairo.FILTER_BILINEAR)
        c.paint()
        c.restore()
        c.set_source_rgba(0, 0, 0, 0.5)
        c.paint()
    oy = max(0.0, (OH - dh) / 2 * 0.86)
    c.save()
    c.rectangle(0, oy, OW, min(dh, OH))
    c.clip()
    c.translate(0, oy)
    c.scale(s, s)
    c.translate(-x0, -y0)
    c.set_source_surface(src, 0, 0)
    c.get_source().set_filter(cairo.FILTER_GOOD)
    c.paint()
    c.restore()


def plan_frames(a, b, teaser):
    """Кадры Shorts → время в ролике: [(время в ролике, время в Shorts)]; тизер — первым."""
    fps = 25
    out = []
    if teaser is not None:
        out += [(teaser + k / fps, k / fps) for k in range(int(TEASER * fps))]
    off = len(out) / fps
    out += [(a + k / fps, off + k / fps) for k in range(int((b - a) * fps))]
    return out


def render_short(video, out, a, b, cams, bands, hook, phrases, teaser=None, work=None):
    """Собрать один Shorts. cams/bands — функции: время ролика → (центр, ширина) и полоса без вшитых субтитров."""
    import cairo

    from . import studio

    fps = 25
    W, H = video_size(video)
    frames = plan_frames(a, b, teaser)
    if not frames:
        raise ShortsError("пустой кусок")
    total = len(frames) / fps
    ow, oh = SIZE
    work = pathlib.Path(work or pathlib.Path(out).parent)
    wav = work / (pathlib.Path(out).stem + ".wav")
    audio_track(video, a, b, teaser, wav, total)
    enc = subprocess.Popen([studio.ffmpeg(), "-hide_banner", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
                            "-s", "{}x{}".format(ow, oh), "-r", str(fps), "-i", "-", "-i", str(wav), "-map", "0:v", "-map", "1:a",
                            "-shortest"] + [str(x) for x in studio.VIDEO_OUT] + [str(x) for x in studio.AUDIO_OUT] +
                           ["-movflags", "+faststart", str(out)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, ow, oh)
    c = cairo.Context(surf)
    acc = accent_word(hook)
    try:
        pieces = ([(teaser, TEASER, 0)] if teaser is not None else []) + \
            [(a, b - a, int(TEASER * fps) if teaser is not None else 0)]
        for start, length, base in pieces:
            dec = subprocess.Popen([studio.ffmpeg(), "-v", "error", "-ss", "{:.3f}".format(start), "-i", str(video), "-t",
                                    "{:.3f}".format(length), "-vf", "fps={}".format(fps), "-f", "rawvideo", "-pix_fmt", "bgra", "-"],
                                   stdout=subprocess.PIPE)
            n = int(round(length * fps))
            for k in range(n):
                raw = dec.stdout.read(W * H * 4)
                if len(raw) < W * H * 4:
                    break
                t_film = start + k / fps
                t_short = (base + k) / fps
                src = cairo.ImageSurface.create_for_data(bytearray(raw), cairo.FORMAT_RGB24, W, H, W * 4)
                c.set_source_rgb(0, 0, 0)
                c.paint()
                compose(c, src, cams(t_film), bands(t_film), (W, H), cairo)
                overlay(c, t_short, total, hook, acc, phrases, t_film, teaser is not None)
                surf.flush()
                enc.stdin.write(bytes(surf.get_data()))
            dec.stdout.close()
            dec.wait()
        enc.stdin.close()
        err = enc.stderr.read().decode("utf-8", "replace")
        if enc.wait(timeout=300) != 0:
            raise ShortsError("ffmpeg: " + (err.strip().splitlines() or ["ошибка"])[-1][:200])
    finally:
        wav.unlink(missing_ok=True)
    return out


def overlay(c, t, total, hook, acc, phrases, t_film, has_teaser):
    """Крючок сверху (появляется рывком, уходит плавно), вспышка на стыке тизера, субтитры в безопасной зоне."""
    if t < HOOK_SECS:
        pop = min(1.0, t / 0.12)
        alpha = 1.0 if t < HOOK_SECS - 0.3 else max(0.0, (HOOK_SECS - t) / 0.3)
        draw_text(c, hook, SIZE[1] * HOOK_Y, 124, acc, alpha, 0.8 + 0.2 * pop + 0.06 * math.sin(min(1.0, t / 0.25) * math.pi))
    if has_teaser and abs(t - TEASER) < FLASH:
        c.set_source_rgba(1, 1, 1, 0.85 * (1 - abs(t - TEASER) / FLASH))
        c.paint()
    if t >= HOOK_SECS * 0.6 or not hook:
        for p0, p1, text in phrases:
            if p0 <= t_film < p1:
                draw_text(c, text, SIZE[1] * CAP_Y, 76)
                break


def video_size(video):
    import re

    from . import studio

    p = subprocess.run([studio.ffmpeg(), "-hide_banner", "-i", str(video)], capture_output=True, text=True)
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", p.stderr)
    if not m:
        raise ShortsError("не читается видео")
    return int(m.group(1)), int(m.group(2))


def audio_track(video, a, b, teaser, out, total):
    """Звук Shorts: тизер (если есть) + кусок, стыки — короткие затухания, в конце — плавный уход."""
    from . import studio

    parts, labels = [], []
    if teaser is not None:
        parts.append("[0:a]atrim={:.3f}:{:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={:.3f}:d=0.08[t]".format(
            teaser, teaser + TEASER, TEASER - 0.08))
        labels.append("[t]")
    parts.append("[0:a]atrim={:.3f}:{:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.03,afade=t=out:st={:.3f}:d=0.35[m]".format(
        a, b, max(0.0, b - a - 0.35)))
    labels.append("[m]")
    graph = ";".join(parts) + ";" + "".join(labels) + "concat=n={}:v=0:a=1[o]".format(len(labels))
    studio.run_ffmpeg(["-i", video, "-filter_complex", graph, "-map", "[o]", "-ar", "44100", "-ac", "2", "-t",
                       "{:.3f}".format(total), out])
    return out


# --- всё вместе ---
def _cam_for_film(folder, scenes, spans, look, mode, frame):
    """Оператор на весь ролик: функции время → (центр, ширина), время → полоса кадра, время → виден ли герой."""
    from . import animator
    from . import studio

    folder = pathlib.Path(folder)
    W, H = frame
    cuts = studio.transition_plan(studio.clean_scenes(scenes))
    per = []
    for i, (s, e) in enumerate(spans):
        sc = scenes[i]
        wf = folder / "words{:02d}.json".format(i)
        words = [tuple(x) for x in json.loads(wf.read_text(encoding="utf-8"))] if wf.exists() else []
        band = caption_band(look, bool(words))
        n = max(1, int(round((e - s) * animator.FPS)))
        cams, vis = [(W / 2, W)] * n, None
        if mode == "anim":
            spec = dict(sc.get("anim") or {})
            for k in ("shot", "beat"):
                if sc.get(k) and not spec.get(k):
                    spec[k] = sc[k]
            lead = studio.LEAD if (i in cuts and words) else 0.0
            try:
                boxes = track_anim(spec, look or "classic_light", e - s, [(x + lead, y + lead, t) for x, y, t in words])
                cams, vis = camera(boxes, band, frame), [bx is not None for bx in boxes]
            except Exception as ex:                                # noqa: BLE001 — не вышло следить — весь кадр
                print("[shorts: сцена {} — оператор не вышел: {}]".format(i + 1, str(ex)[:80]))
        per.append((s, e, cams, band, vis))

    def find(t):
        return next((p for p in per if p[0] <= t < p[1]), per[-1])

    def idx(p, t, seq):
        return seq[min(len(seq) - 1, max(0, int((t - p[0]) * animator.FPS)))]

    def cam(t):
        p = find(t)
        return idx(p, t, p[2])

    def band(t):
        return find(t)[3]

    def seen(t):
        p = find(t)
        return True if p[4] is None else idx(p, t, p[4])
    return cam, band, seen


def make_shorts(folder, video, script, mode="anim", look=None, ask=None, count=None, out_dir=None, progress=print):
    """Готовый ролик → Shorts в папке «к публикации/shorts» + shorts.txt. Возвращает [(путь, начало, конец, крючок)]."""
    from . import publish

    folder = pathlib.Path(folder)
    scenes = script.get("scenes") or []
    spans = scene_spans(folder, len(scenes))
    if not spans:
        raise ShortsError("нет клипов сцен в папке проекта")
    W, H = video_size(video)
    if H > W:
        raise ShortsError("ролик уже вертикальный — он сам годится в Shorts")
    en = energy(video)
    total = spans[-1][1]
    chosen = choose(candidates(spans, en), count or default_count(total))
    parts = []
    for a, b, _sc in chosen:
        ids = [i for i, (s, e) in enumerate(spans) if s < b and e > a]
        parts.append("; ".join(filter(None, [(scenes[i].get("narration") or "").strip() or
                                             "без слов: " + ", ".join(x.get("do", "") for x in (scenes[i].get("anim") or {}).get("acting", [])[:6])
                                             for i in ids]))[:500])
    hooks = hook_texts(script, parts, ask)
    cam, band, seen = _cam_for_film(folder, scenes, spans, look, mode, (W, H))
    phrases = publish.film_phrases(folder, scenes)
    out_dir = pathlib.Path(out_dir or folder / publish.FOLDER / "shorts")
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for n, ((a, b, _sc), hook) in enumerate(zip(chosen, hooks), 1):
        teaser = teaser_at(en, a, b, seen=seen)
        out = out_dir / "short-{}.mp4".format(n)
        progress("Shorts {} из {}: {:.0f}–{:.0f} с{}".format(n, len(chosen), a, b, ", с тизером" if teaser is not None else ""))
        render_short(video, out, a, b, cam, band, hook, phrases, teaser, out_dir)
        made.append((out, a, b, hook, teaser))
    write_notes(out_dir, script, made)
    return made


NOTES = """SHORTS — загружать как обычное видео (YouTube сам поймёт по вертикали 9:16 и длине до 3 минут).

{items}
ПЕРЕД ЗАГРУЗКОЙ:
[ ] В названии — #Shorts (уже есть) и крючок; описание — одна строка
[ ] «Связанное видео» (в редакторе Shorts) — укажи полный ролик: зрители Shorts перейдут на него
[ ] Не выкладывай все Shorts в один день: по одному в 1–2 дня держат канал живым
[ ] Музыка — только своя или из Фонотеки YouTube (иначе Content ID)
"""


def write_notes(out_dir, script, made):
    title = (script.get("title") or "").strip()
    items = ""
    for path, a, b, hook, teaser in made:
        name = "{} #Shorts".format(hook if hook and hook != title else title)[:100]
        items += "{}  ({:.0f}–{:.0f} с ролика{})\n  НАЗВАНИЕ: {}\n  ОПИСАНИЕ: {} Полная версия — на канале.\n\n".format(
            path.name, a, b, ", в начале — тизер" if teaser is not None else "", name, (script.get("logline") or title).strip())
    (pathlib.Path(out_dir) / "shorts.txt").write_text(NOTES.format(items=items), encoding="utf-8")
