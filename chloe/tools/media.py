"""Инструмент create_media — нарисовать картинку или сделать видео (Qwen). Работает в фоне: Chloe не молчит минуту."""
import itertools
import subprocess
import threading
import time

from .. import qwen_media as qm
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


def _run(job_id, kind, work, open_result=True):
    job = jobs[job_id]
    try:
        paths = work()
        paths = paths if isinstance(paths, list) else [paths]
        job.update(state="готово", result=[qm.short(p) for p in paths])
        if open_result:
            show(paths[0])
        _say("{} готов{}: {}.".format("Картинка" if kind == "image" else "Видео", "а" if kind == "image" else "о",
                                       ", ".join(job["result"])))
    except qm.MediaError as e:
        job.update(state="ошибка", result=str(e))
        _say("{} не получил{}: {}.".format("Картинка" if kind == "image" else "Видео", "ась" if kind == "image" else "ось",
                                          str(e).rstrip(".")))
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
            lines.append("#{} {} «{}» — {}{}".format(i, "картинка" if j["kind"] == "image" else "видео", j["prompt"][:50],
                                                    j["state"], " ({} мин)".format(mins) if j["state"] == "работаю"
                                                    else ": {}".format(res)))
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
        if not confirm("Сделать видео {} секунд{}? Видео тратит заметно больше кредитов Qwen, чем картинка.".format(
                seconds, " из картинки" if source else "")):
            return "Не делаю видео."
        try:
            task = qm.video_start(prompt, source, seconds, res, a.get("ratio") or "16:9")
        except qm.MediaError as e:
            return "Видео не началось: {}.".format(e)
        job = _start("video", prompt, lambda: qm.video_wait(task, prompt), open_result)
        return ("Видео поставлено в очередь Alibaba (#{}): обычно 2–5 минут. Когда будет готово — скажу и открою. "
                "Файлы — в {}.".format(job, qm.short(qm.VIDEO_DIR)))
    return "Неизвестное действие: " + action
