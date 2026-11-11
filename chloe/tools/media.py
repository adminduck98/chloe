"""Инструменты create_media (картинка или видео через Qwen) и make_film (ролик из идеи: сцены, озвучка, склейка).
Работают в фоне: Chloe не молчит минуты, а говорит, когда готово."""
import itertools
import subprocess
import threading
import time

from .. import qwen_media as qm
from .. import audiobook, screenplay, studio
from ..voice import confirm

jobs = {}                 # номер → {"kind", "prompt", "state": "работаю"/"готово"/"ошибка", "result", "started"}
_ids = itertools.count(1)
_lock = threading.Lock()


def show(path):
    try:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def _say(text):
    from ..voice import voice

    print("[медиа] " + text)
    voice.say(text)


NAMES = {"image": ("Картинка", "готова", "не получилась"), "video": ("Видео", "готово", "не получилось"),
         "film": ("Ролик", "готов", "не получился"), "audio": ("Озвучка", "готова", "не получилась")}


def _run(job_id, kind, work, open_result=True):
    job = jobs[job_id]
    name, ok, bad = NAMES[kind]
    try:
        paths = work()
        paths = paths if isinstance(paths, list) else [paths]
        job.update(state="готово", result=[qm.short(p) for p in paths])
        if open_result:
            show(paths[0])
        _say("{} {}: {}.".format(name, ok, ", ".join(job["result"])))
    except (qm.MediaError, studio.StudioError, audiobook.AudioError) as e:
        job.update(state="ошибка", result=str(e))
        _say("{} {}: {}.".format(name, bad, str(e).rstrip(".")))
    except Exception as e:   # фоновая работа не должна молча умирать
        job.update(state="ошибка", result=repr(e)[:200])
        _say("Что-то сломалось при создании: {}.".format(type(e).__name__))


def _start(kind, prompt, work, open_result=True):
    with _lock:
        job_id = next(_ids)
        jobs[job_id] = {"kind": kind, "prompt": prompt, "state": "работаю", "result": None, "started": time.time()}
    threading.Thread(target=_run, args=(job_id, kind, work, open_result), daemon=True).start()
    return job_id


def tool_create_media(a):
    action = a.get("action", "image")
    if action == "status":
        if not jobs:
            return "Сейчас ничего не рисую и видео не делаю."
        lines = []
        for i, j in sorted(jobs.items())[-10:]:
            mins = int((time.time() - j["started"]) // 60)
            res = j["result"] if j["state"] != "готово" else ", ".join(j["result"])
            lines.append("#{} {} «{}» — {}{}{}".format(i, NAMES[j["kind"]][0].lower(), j["prompt"][:50], j["state"],
                                                      " ({} мин)".format(mins) if j["state"] == "работаю" else ": {}".format(res),
                                                      ", " + j["step"] if j.get("step") and j["state"] == "работаю" else ""))
        return "\n".join(lines)

    if not qm.available():
        return "Нет ключа Qwen (DASHSCOPE_API_KEY в ~/.config/chloe/keys.env) — рисовать не на чем."
    prompt = (a.get("prompt") or "").strip()
    source = (a.get("image") or "").strip() or None
    if not prompt:
        return "Нужно описание (prompt): что нарисовать или что должно происходить в видео."
    open_result = a.get("open", True) is not False

    if action == "image":
        n = a.get("count") or 1
        ratio = a.get("ratio") or "1:1"
        if source:
            try:
                qm._image_ref(source)            # нет файла — скажем сразу, а не через минуту
            except qm.MediaError as e:
                return "Не могу: {}.".format(e)
        job = _start("image", prompt, lambda: qm.image(prompt, ratio, n, source), open_result)
        return ("Начала {} (#{}): это 30–90 секунд, когда будет готово — скажу и открою. "
                "Файлы — в {}.".format("менять картинку" if source else "рисовать", job, qm.short(qm.IMAGE_DIR)))

    if action == "video":
        seconds = max(3, min(int(a.get("seconds") or 5), 15))
        res = (a.get("resolution") or "720P").upper()
        res = res if res in ("720P", "1080P") else "720P"
        if source:
            try:
                qm._image_ref(source)
            except qm.MediaError as e:
                return "Не могу: {}.".format(e)
        # замер 10.11.2026: 5 с 720P ≈ 4,5 % месячного Token Plan; 1080P у Alibaba ≈ в 1,8 раза дороже
        cost = 0.9 * seconds * (1.8 if res == "1080P" else 1)
        if not confirm("Сделать видео {} секунд{}? Это примерно {:.0f} % месячного пакета Qwen.".format(
                seconds, " из картинки" if source else "", max(1, cost))):
            return "Не делаю видео."
        try:
            task = qm.video_start(prompt, source, seconds, res, a.get("ratio") or "16:9")
        except qm.MediaError as e:
            return "Видео не началось: {}.".format(e)
        job = _start("video", prompt, lambda: qm.video_wait(task, prompt), open_result)
        return ("Видео поставлено в очередь Alibaba (#{}): обычно 2–5 минут. Когда будет готово — скажу и открою. "
                "Файлы — в {}.".format(job, qm.short(qm.VIDEO_DIR)))
    return "Неизвестное действие: " + action


def tool_make_film(a):
    if not qm.available():
        return "Нет ключа Qwen (DASHSCOPE_API_KEY в ~/.config/chloe/keys.env) — рисовать сцены не на чем."
    scenes = studio.clean_scenes(a.get("scenes"))
    idea = (a.get("idea") or "").strip()
    style = (a.get("style") or "").strip()
    title = (a.get("title") or "").strip()
    if idea and not scenes:
        # сценарий пишет сценарист (поиск + сильная модель + редактор), а не быстрый мозг на лету
        _say("Пишу сценарий: поищу в интернете, придумаю героев и сюжет — это около двух минут.")
        try:
            script = screenplay.write(idea, a.get("notes") or "")
        except Exception as e:
            return "Не смогла написать сценарий: {}. Попробуйте ещё раз или продиктуйте свои сцены.".format(str(e)[:150])
        scenes, title = script["scenes"], title or script["title"]
        style = (style + " " if style else "") + screenplay.style_line(script)
    if not scenes:
        return ("Нужен сценарий: передай idea — идею пользователя его словами (сценарий напишет сценарист), "
                "или scenes — готовые сцены, у каждой picture (описание кадра) и narration (закадровая фраза).")
    title = title or scenes[0]["picture"][:40]
    mode = "live" if a.get("mode") == "live" else "slides"
    ratio = a.get("ratio") if a.get("ratio") in studio.FRAMES else "16:9"
    try:
        studio.ffmpeg()
    except studio.StudioError as e:
        return "Не могу собрать ролик: {}.".format(e)
    cost = studio.estimate(scenes, mode)
    plan = "; ".join("{}) {}".format(i + 1, s["narration"] or s["picture"][:60]) for i, s in enumerate(scenes))
    if not confirm("Сделать ролик «{}» из {} сцен, {}? Это примерно {:.0f} % месячного пакета Qwen. Сцены: {}".format(
            title, len(scenes), "с живым видео" if mode == "live" else "слайдами с озвучкой", max(1, cost), plan)):
        return "Не делаю ролик."
    open_result = a.get("open", True) is not False
    holder = {}

    def progress(text):
        job = jobs.get(holder.get("id"))
        if job:
            job["done"] = job.get("done", 0) + 1
            job["step"] = "готово сцен: {} из {}".format(job["done"], len(scenes))

    job = _start("film", title, lambda: studio.make_film(title, scenes, style, ratio, mode, progress),
                 open_result)
    holder["id"] = job
    return ("Начала ролик (#{}): {} сцен, {}. Когда будет готово — скажу и открою. Файл — в {}. "
            "Как идёт — create_media status.".format(job, len(scenes), "это 10–20 минут" if mode == "live" else "это 2–4 минуты",
                                                    qm.short(qm.VIDEO_DIR)))


LONG = 30        # минут звука: дольше — сначала спросить


def tool_narrate(a):
    text = (a.get("text") or "").strip()
    path = (a.get("path") or "").strip()
    if not text and not path:
        return "Нужен text (что озвучить) или path (документ или книга: PDF, Word, EPUB, FB2, TXT, Markdown, HTML)."
    try:
        if path:
            text = audiobook.read_text(path)
        studio.ffmpeg()
    except (audiobook.AudioError, studio.StudioError) as e:
        return "Не могу: {}.".format(e)
    import pathlib

    title = (a.get("title") or "").strip() or (pathlib.Path(path).stem if path else text[:40])
    voice = audiobook.VOICES.get((a.get("voice") or "svetlana").lower().strip(), "ru-RU-SvetlanaNeural")
    cleaned = audiobook.clean(text)
    if not cleaned:
        return "В тексте нечего озвучивать."
    split = a.get("chapters", True) is not False
    parts = len(audiobook.chapters(cleaned)) if split else 1
    mins = audiobook.minutes(len(cleaned) / (float(a.get("speed") or 1) or 1))
    work = max(1, round(mins / 6))   # замер 10.11.2026: 4 куска параллельно — в 6 раз быстрее звучания (Qwen — по одному)
    if voice == "qwen":
        work = max(1, round(mins / 1.5))
    what = "{} мин звука{}, запись займёт около {} мин".format(mins, ", {} глав".format(parts) if parts > 1 else "", work)
    if voice == "qwen" or mins > LONG:
        extra = " Голос Qwen тратит кредиты Token Plan." if voice == "qwen" else ""
        if not confirm("Озвучить «{}»: {}.{} Начать?".format(title, what, extra)):
            return "Не озвучиваю."
    holder = {}

    def progress(done, total):
        job = jobs.get(holder.get("id"))
        if job:
            job["step"] = "озвучено {} %".format(done * 100 // total)

    job = _start("audio", title, lambda: audiobook.record(cleaned, title, voice, a.get("speed") or 1.0, progress,
                                                          split_chapters=split),
                 a.get("open", False) is True)
    holder["id"] = job
    return ("Начала озвучку (#{}): «{}», {}. Когда будет готово — скажу. Файлы — в {}. "
            "Как идёт — create_media status.".format(job, title, what, qm.short(audiobook.AUDIO_DIR)))
