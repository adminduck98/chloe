"""Voice Studio — озвучка текста и аудиокниги: текст или документ → mp3.

Документ читается так же, как для базы знаний (PDF, Word, тексты, Markdown, HTML), плюс книги EPUB и FB2.
Текст чистится (переносы, номера страниц), делится на куски по предложениям, каждый кусок озвучивается
(несколько параллельно), потом куски склеиваются ffmpeg-ом без перекодирования.
Если в книге есть главы («Глава 1», «Часть вторая», «Chapter 3») — по файлу на главу в своей папке.
Голоса: Светлана и Дмитрий (Microsoft, бесплатно), qwen — голос Qwen (тратит кредиты Token Plan).
Файлы — в «Музыка/Chloe».
"""
import asyncio
import pathlib
import re
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

from .config import user_dir

AUDIO_DIR = user_dir("MUSIC", "Music") / "Chloe"
VOICES = {"svetlana": "ru-RU-SvetlanaNeural", "светлана": "ru-RU-SvetlanaNeural",
          "dmitry": "ru-RU-DmitryNeural", "дмитрий": "ru-RU-DmitryNeural", "qwen": "qwen", "квен": "qwen"}
PIECE = 1500             # знаков в куске: длиннее — сервер голоса чаще обрывается
CHARS_PER_MIN = 900      # русская речь: примерно столько знаков в минуту
MAX_CHARS = 2_000_000
BOOK_EXT = {".epub", ".fb2"}
ATTEMPTS = 8
BACKOFF = 1.0            # множитель пауз между повторами (в тестах — 0)
CHAPTER = re.compile(r"^\s*((?:глава|часть|chapter|part)\s+[\wIVXLC]+\b.{0,80}|пролог|эпилог|prologue|epilogue)\s*$",
                     re.I | re.M)


class AudioError(Exception):
    pass


# --- текст ---
def _xml_text(raw):
    import html

    raw = re.sub(r"(?is)<(script|style|binary)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<(h\d|title)\b", "\n\n<\\1", raw)                       # заголовок — с новой строки
    raw = re.sub(r"(?i)</(p|div|h\d|title|section|li)>", "\n\n", raw)          # абзацы — через пустую строку
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    return html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))


def read_book(p):
    if p.suffix.lower() == ".fb2":
        return _xml_text(p.read_text(encoding="utf-8", errors="replace"))
    with zipfile.ZipFile(p) as z:                     # EPUB: главы — xhtml-файлы в порядке из content.opf
        names = z.namelist()
        opf = next((n for n in names if n.endswith(".opf")), None)
        order = []
        if opf:
            text = z.read(opf).decode("utf-8", "replace")
            items = dict(re.findall(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', text))
            items.update({k: v for v, k in re.findall(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', text)})
            base = opf.rsplit("/", 1)[0] + "/" if "/" in opf else ""
            order = [base + items[i] for i in re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', text) if i in items]
        order = [n for n in order if n in names] or sorted(n for n in names if n.endswith((".xhtml", ".html", ".htm")))
        return "\n".join(_xml_text(z.read(n).decode("utf-8", "replace")) for n in order)


def read_text(path):
    p = pathlib.Path(path).expanduser()
    if not p.is_file():
        raise AudioError("нет файла {}".format(p))
    ext = p.suffix.lower()
    try:
        if ext in BOOK_EXT:
            text = read_book(p)
        else:
            from .knowledge import SUPPORTED, extract

            if ext not in SUPPORTED:
                raise AudioError("не умею читать {} — нужен PDF, Word, EPUB, FB2, TXT, Markdown или HTML".format(ext or "этот файл"))
            text = "\n".join(t for _, t in extract(p))
    except AudioError:
        raise
    except Exception as e:
        raise AudioError("не удалось прочитать {} ({})".format(p.name, type(e).__name__)) from None
    if not text.strip():
        raise AudioError("в файле нет текста (возможно, это скан — картинки вместо букв)")
    return text


def clean(text):
    """Переносы слов и строк из PDF, номера страниц, разметка Markdown — прочь; абзацы остаются."""
    text = text.replace("\r", "").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)                    # пере-\nнос
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", text)                  # номер страницы отдельной строкой
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)                # заголовки Markdown
    text = re.sub(r"[*_`~]{1,3}([^*_`~\n]+)[*_`~]{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)             # [ссылка](адрес) → ссылка
    text = re.sub(r"https?://\S+", "", text)                         # адреса вслух никто слушать не хочет
    text = CHAPTER.sub(lambda m: "\n\n" + m.group(0).strip() + "\n\n", text)   # заголовок главы — отдельным абзацем
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    if len(paras) <= 2:                                              # PDF: абзацы не размечены — склеиваем строки
        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n(?=[А-ЯЁA-Z—–-])", text)]
    return "\n\n".join(p for p in paras if p)


def chapters(text):
    """[(название, текст)] — по главам, если их хотя бы две; иначе одна часть без названия."""
    marks = list(CHAPTER.finditer(text))
    if len(marks) < 2:
        return [("", text)]
    parts = []
    if text[:marks[0].start()].strip():
        parts.append(("Начало", text[:marks[0].start()]))
    for m, nxt in zip(marks, marks[1:] + [None]):
        body = text[m.end():nxt.start() if nxt else len(text)]
        if body.strip():
            title = re.sub(r"\s+", " ", m.group(1)).strip()
            parts.append((title, title + ".\n\n" + body))
    return parts


def pieces(text, size=PIECE):
    """Куски не длиннее size, по границам предложений (слишком длинное предложение режется по запятым и словам)."""
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?…»])\s+|\n+", text):
        sent = sent.strip()
        while len(sent) > size:
            cut = max(sent.rfind(", ", 0, size), sent.rfind(" ", 0, size))
            cut = cut if cut > size // 3 else size
            head, sent = sent[:cut + 1].strip(), sent[cut + 1:].strip()
            if cur:
                out.append(cur)
                cur = ""
            out.append(head)
        if not sent:
            continue
        if cur and len(cur) + 1 + len(sent) > size:
            out.append(cur)
            cur = sent
        else:
            cur = (cur + " " + sent).strip()
    if cur:
        out.append(cur)
    return out


def minutes(chars):
    return max(1, round(chars / CHARS_PER_MIN))


# --- голос ---
def _edge(text, voice, rate, timeout=90):
    import edge_tts

    async def go():
        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return bytes(buf)

    problem = None
    # сервер иногда отвечает без звука или обрывает связь, бывает — полминуты подряд. Один сбой не должен
    # обрывать двухчасовую книгу: пробуем 8 раз, паузы растут до 10 с (всего около минуты)
    for attempt in range(ATTEMPTS):
        try:
            data = asyncio.run(asyncio.wait_for(go(), timeout))
            if data:
                return data
        except Exception as e:
            problem = e
        if attempt < ATTEMPTS - 1:
            time.sleep(min(10, 1 + 2 * attempt) * BACKOFF)
    raise AudioError("голос Microsoft не отвечает ({})".format(type(problem).__name__ if problem else "пусто"))


def speak(text, voice="ru-RU-SvetlanaNeural", rate="+0%"):
    if voice == "qwen":
        from . import qwen_audio

        try:
            return qwen_audio.tts_mp3(text, timeout=90)
        except Exception as e:
            raise AudioError("голос Qwen: {}".format(str(e)[:100])) from None
    return _edge(text, voice, rate)


def _rate(speed):
    """«быстрее» 1.2 → +20%; 0.8 → -20%."""
    try:
        pct = round((float(speed or 1) - 1) * 100)
    except (TypeError, ValueError):
        pct = 0
    pct = max(-50, min(100, pct))
    return "{:+d}%".format(pct)


def _join(parts, out):
    from .studio import run_ffmpeg

    lst = pathlib.Path(out).with_suffix(".txt")
    lst.write_text("".join("file '{}'\n".format(str(p).replace("'", "'\\''")) for p in parts), encoding="utf-8")
    try:
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
    finally:
        lst.unlink(missing_ok=True)


def _slug(text):
    words = re.findall(r"\w+", text.lower())[:6]
    return "-".join(words)[:50] or "озвучка"


def record(text, title, voice="ru-RU-SvetlanaNeural", speed=1.0, progress=lambda done, total: None, workers=4,
           split_chapters=True):
    """Озвучить. Возвращает список mp3: один файл или по файлу на главу (в отдельной папке)."""
    text = clean(text)
    if not text:
        raise AudioError("нет текста для озвучки")
    if len(text) > MAX_CHARS:
        raise AudioError("текст слишком длинный ({} знаков, можно до {})".format(len(text), MAX_CHARS))
    rate = _rate(speed)
    parts = chapters(text) if split_chapters else [("", text)]
    jobs = [(ci, pi, piece) for ci, (_, body) in enumerate(parts) for pi, piece in enumerate(pieces(body))]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if len(parts) > 1:
        folder = AUDIO_DIR / "{}-{}".format(stamp, _slug(title))
        names = [folder / "{:02d} {}.mp3".format(i + 1, re.sub(r'[\\/:*?"<>|]', "", t)[:60].strip()) for i, (t, _) in enumerate(parts)]
    else:
        folder = AUDIO_DIR
        names = [folder / "{}-{}.mp3".format(stamp, _slug(title))]
    done = [0]
    with tempfile.TemporaryDirectory(prefix="chloe-audio-") as tmp:
        work = pathlib.Path(tmp)

        def one(job):
            ci, pi, piece = job
            path = work / "{:03d}-{:05d}.mp3".format(ci, pi)
            path.write_bytes(speak(piece, voice, rate))
            done[0] += 1
            progress(done[0], len(jobs))
            return path

        try:
            first = one(jobs[0])        # первый кусок — отдельно: голос не работает — узнаем сразу, а не через час
        except AudioError as e:
            hint = " — попробуйте позже или другим голосом (Светлана, Qwen)" if voice != "qwen" else ""
            raise AudioError("{}{}".format(e, hint)) from None
        with ThreadPoolExecutor(max_workers=1 if voice == "qwen" else workers) as pool:
            files = [first] + list(pool.map(one, jobs[1:]))
        folder.mkdir(parents=True, exist_ok=True)
        for ci, out in enumerate(names):
            _join([f for (c, _, _), f in zip(jobs, files) if c == ci], out)
    return names
