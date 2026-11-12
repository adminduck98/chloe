"""Инструменты create_media (картинка или видео через Qwen) и make_film (ролик из идеи: сцены, озвучка, склейка).
Работают в фоне: Chloe не молчит минуты, а говорит, когда готово."""
import itertools
import os
import pathlib
import json
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
         "film": ("Ролик", "готов (обложки, описание, теги и субтитры для YouTube — в папке проекта «к публикации»)", "не получился"), "audio": ("Озвучка", "готова", "не получилась"),
         "preview": ("Пробный кусок ролика", "готов — посмотрите и скажите «делай весь ролик» или что поправить", "не получился")}


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
        ratio = a.get("ratio") or (None if source else "1:1")      # правка картинки — её форма, если форму не назвали
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


def storyboard(script, scenes, ratio, out_dir=None):
    """Режим «раскадровка»: сценарий, кадры и готовые подсказки для любого генератора видео — файлом, без кредитов."""
    from .. import stickman_styles as ST

    out_dir = out_dir or (qm.VIDEO_DIR / "раскадровки")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "{}-{}".format(time.strftime("%Y%m%d-%H%M%S"), qm._slug(script.get("title") or "ролик"))
    style = ST.STYLES.get(script.get("style_key"), ST.STYLES[ST.DEFAULT])
    stages = {"hook": "крючок", "myth": "ломаем привычное", "secret": "скрытая деталь", "truth": "главная правда", "finale": "финал"}
    lines = ["# {}".format(script.get("title") or "Ролик"), "",
             "**Логлайн:** {}".format(script.get("logline") or "—"),
             "**Стиль:** {} · **Формат:** {} · **Сцен:** {} · **Длина:** около {} с".format(
                 style["name"], ratio, len(scenes), round(sum(studio.scene_seconds(s) for s in scenes))),
             "**Паспорт героя (вставлен в каждый кадр дословно):** {}".format(script.get("characters") or style["anchor"]),
             "**Музыка:** {}".format(style["music"]), ""]
    t = 0.0
    for i, sc in enumerate(scenes, 1):
        secs = studio.scene_seconds(sc)
        lines += ["## Сцена {} · {:.0f}–{:.0f} с{}".format(i, t, t + secs, " · " + stages[sc["stage"]] if sc.get("stage") in stages else ""),
                  "", "**Голос:** {}".format(sc.get("narration") or "—")]
        if sc.get("beats"):
            lines.append("**Действия:** " + " → ".join(sc["beats"]))
        lines += ["", "**Первый кадр (картинка):**", "```", sc["picture"], "```",
                  "**Видео (подсказка для генератора, ~{:.0f} с):**".format(secs), "```", sc.get("video") or sc["picture"], "```", ""]
        t += secs
    md = out_dir / (stem + ".md")
    md.write_text("\n".join(lines), encoding="utf-8")
    (out_dir / (stem + ".json")).write_text(json.dumps(dict(script, scenes=scenes, ratio=ratio), ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    return md


def tool_make_film(a):
    from .. import stickman_styles as ST

    mode = a.get("mode") if a.get("mode") in ("slides", "live", "director", "anim") else "slides"
    ratio = a.get("ratio") if a.get("ratio") in studio.FRAMES else "16:9"
    if a.get("action") == "continue":
        return _continue_film(a)
    if mode == "anim":
        from .. import animator

        if not animator.available():
            return "Мультипликатору нужна библиотека cairo: sudo apt install python3-cairo (или pip install pycairo)."
    if mode not in ("director", "anim") and not qm.available():
        return "Нет ключа Qwen (DASHSCOPE_API_KEY в ~/.config/chloe/keys.env) — рисовать сцены не на чем."
    scenes = studio.clean_scenes(a.get("scenes"))
    idea = (a.get("idea") or "").strip()
    style_words = (a.get("style") or "").strip()
    style_key = ST.find(style_words)
    title = (a.get("title") or "").strip()
    script = None
    if idea and not scenes:
        # сценарий пишет сценарист-режиссёр (поиск + сильная модель + редактор), а не быстрый мозг на лету
        _say("Пишу сценарий: поищу в интернете, придумаю сюжет и кадры — это около двух минут.")
        try:
            script = screenplay.write(idea, a.get("notes") or "", a.get("duration") or 60, style_key=style_key, anim=mode == "anim")
        except Exception as e:
            return "Не смогла написать сценарий: {}. Попробуйте ещё раз или продиктуйте свои сцены.".format(str(e)[:150])
        scenes, title = screenplay.frames(script), title or script["title"]
        style_extra = ""
    else:
        # готовые сцены пользователя: паспорт героя и мир стиля — тоже в каждый кадр, если стиль назван
        if style_key:
            scenes = [dict(sc, picture=ST.frame(sc["picture"], style_key)) for sc in scenes]
        style_extra = "" if style_key else style_words
        script = {"title": title, "logline": "", "style_key": style_key or ST.DEFAULT, "characters": ""}
    if not scenes:
        return ("Нужен сценарий: передай idea — идею пользователя его словами (сценарий напишет сценарист), "
                "или scenes — готовые сцены, у каждой picture (описание кадра) и narration (закадровая фраза).")
    title = title or scenes[0]["picture"][:40]
    if mode == "director":
        md = storyboard(script, scenes, ratio)
        if a.get("open", True) is not False:
            show(md)
        return ("Раскадровка готова (кредиты не тратились): «{}», {} сцен, стиль «{}». Файл {} — там голос, действия и подсказки "
                "для генератора видео к каждой сцене. Скажи пользователю коротко о сюжете и спроси: делать ролик самой "
                "(make_film с теми же сценами) или он возьмёт подсказки в свой генератор.".format(
                    title, len(scenes), ST.STYLES.get(script["style_key"], ST.STYLES[ST.DEFAULT])["name"], qm.short(md)))
    try:
        studio.ffmpeg()
    except studio.StudioError as e:
        return "Не могу собрать ролик: {}.".format(e)
    look = script.get("style_key") or ST.DEFAULT
    if mode == "anim" and look in studio.BG_LOOKS and not qm.available():
        return "Для стиля «{}» фоны мест рисует Qwen, а ключа нет. Выбери классический, тёмный или неоновый стиль.".format(
            ST.STYLES[look]["name"])
    full = a.get("preview") is False
    upto = len(scenes) if full else studio.preview_count(scenes)
    whole = studio.estimate(scenes, mode, look)
    part = studio.estimate(scenes[:upto], mode, look)
    plan = "; ".join("{}) {}".format(i + 1, s["narration"] or s["picture"][:60]) for i, s in enumerate(scenes))
    what = {"live": "с живым видео", "anim": "мультфильмом (человечки двигаются, голос, субтитры)"}.get(
        mode, "слайдами с озвучкой и субтитрами")
    if mode == "anim" and whole < 0.5:                       # свой мультипликатор — бесплатно: спрашивать о цене нечего
        folder = studio.new_project(title, scenes, style_extra, ratio, mode, {"script": script, "look": look})
        upto = len(scenes) if full or len(scenes) <= 3 else studio.preview_count(scenes)
        return _launch(folder, title, scenes, style_extra, ratio, mode, upto, a.get("open", True) is not False, look)
    if upto < len(scenes):
        question = ("Ролик «{}»: {} сцен, {}. Сначала пробный кусок — {} сцены (~20 секунд), примерно {:.0f} % месячного пакета Qwen; "
                    "весь ролик потом — ещё около {:.0f} %. Сцены: {}").format(title, len(scenes), what, upto, max(1, part),
                                                                           max(1, whole - part), plan)
    else:
        question = "Сделать ролик «{}» из {} сцен, {}? Это примерно {:.0f} % месячного пакета Qwen. Сцены: {}".format(
            title, len(scenes), what, max(1, whole), plan)
    if not confirm(question):
        return "Не делаю ролик."
    folder = studio.new_project(title, scenes, style_extra, ratio, mode, {"script": script, "look": look})
    return _launch(folder, title, scenes, style_extra, ratio, mode, upto, a.get("open", True) is not False, look)


def _launch(folder, title, scenes, style, ratio, mode, upto, open_result=True, look=None):
    holder = {}

    def progress(text):
        job = jobs.get(holder.get("id"))
        if job:
            job["done"] = job.get("done", 0) + 1
            job["step"] = "готово сцен: {} из {}".format(job["done"], upto)

    kind = "preview" if upto < len(scenes) else "film"
    job = _start(kind, title, lambda: studio.make_film(title, scenes, style, ratio, mode, progress, project=folder, upto=upto,
                                                       look=look), open_result)
    holder["id"] = job
    if kind == "preview":
        return ("Начала пробный кусок (#{}): первые {} сцены со звуком и субтитрами. Когда будет готово — скажу и открою. "
                "Весь ролик — после слов пользователя «делай весь ролик» (make_film action=continue).".format(job, upto))
    return ("Начала ролик (#{}): {} сцен, {}. Когда будет готово — скажу и открою. Файл — в {}. Как идёт — create_media status."
            .format(job, len(scenes), {"live": "это 10–20 минут", "anim": "это пара минут, кредиты не тратятся"}.get(
                mode, "это несколько минут"), qm.short(qm.VIDEO_DIR)))


def _continue_film(a):
    """«Делай весь ролик»: доделать последний (или названный) проект после пробного куска; готовые сцены не переделываются."""
    try:
        p = studio.load_project(a.get("project") or None)
    except studio.StudioError as e:
        return "Не могу: {}.".format(e)
    scenes, mode = p["scenes"], p.get("mode", "slides")
    done = len(list(p["folder"].glob("clip*.mp4"))) - len(list(p["folder"].glob("clip*.part.mp4")))
    rest = scenes[done:]
    if not rest:
        return "Ролик «{}» уже сделан целиком — он в {}.".format(p["title"], qm.short(qm.VIDEO_DIR))
    look = p.get("look")
    cost = studio.estimate(rest, mode, look)
    if cost >= 0.5 and not confirm("Доделать ролик «{}»: ещё {} сцен из {}, примерно {:.0f} % месячного пакета Qwen?".format(
            p["title"], len(rest), len(scenes), max(1, cost))):
        return "Не доделываю."
    return _launch(p["folder"], p["title"], scenes, p.get("style", ""), p.get("ratio", "16:9"), mode, len(scenes),
                   a.get("open", True) is not False, look)


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



def tool_learn_move(a):
    """Видео пользователя → своё движение стикмена (chloe/video_mocap.py)."""
    import json as _json

    from .. import video_mocap as VM

    if a.get("action") == "list":
        path = VM.user_path()
        names = sorted(_json.loads(path.read_text(encoding="utf-8"))["moves"]) if path.exists() else []
        return "Свои движения: {}.".format(", ".join(names)) if names else "Своих движений пока нет — пришлите видео."
    path = pathlib.Path(os.path.expanduser(str(a.get("path") or ""))).resolve() if a.get("path") else None
    if not path or not path.is_file():
        return "Нужно видео: путь к файлу (лучше снято сбоку, во весь рост, 3–15 секунд)."
    name = str(a.get("name") or path.stem)
    try:
        key, secs, (found, total) = VM.learn(path, name, None if a.get("mirror") is None else bool(a.get("mirror")))
    except VM.VideoMocapError as e:
        return "Не получилось: {}.".format(e)
    return ("Выучила движение «{}»: {} с, человек найден на {} кадрах из {}. В мультфильме — do: \"{}\" "
            "(с мультяшным фильтром в стиле action).".format(key, secs, found, total, key))
