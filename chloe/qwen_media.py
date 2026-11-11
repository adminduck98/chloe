"""Картинки и видео через Qwen (Alibaba Model Studio): qwen-image / wan — картинки, happyhorse / wan — видео.

С подпиской Token Plan (ключ sk-sp-…) тратятся кредиты подписки, с обычным ключом — деньги по факту.
Картинка готова за 10–40 с (ждём ответа сразу). Видео делается несколько минут: задача ставится в очередь,
Chloe следит за ней в фоне, скачивает готовый файл и говорит об этом. Ссылки Alibaba живут сутки —
файлы сразу сохраняются в «Изображения/Chloe» и «Видео/Chloe».
"""
import base64
import json
import mimetypes
import os
import pathlib
import re
import time
import urllib.error
import urllib.request

from . import config
from .config import HOME, user_dir

IMAGE_MODEL = os.environ.get("CHLOE_IMAGE_MODEL", "qwen-image-3.0-pro")
VIDEO_MODEL = os.environ.get("CHLOE_VIDEO_MODEL", "happyhorse-1.1-t2v")         # видео по описанию
I2V_MODEL = os.environ.get("CHLOE_I2V_MODEL", "happyhorse-1.1-i2v")             # оживить картинку
IMAGE_DIR = user_dir("PICTURES", "Pictures") / "Chloe"
VIDEO_DIR = user_dir("VIDEOS", "Videos") / "Chloe"
SIZES = {"1:1": "1328*1328", "16:9": "1664*928", "9:16": "928*1664", "4:3": "1472*1104", "3:4": "1104*1472"}
VIDEO_WAIT = 15 * 60      # дольше видео не ждём


class MediaError(Exception):
    pass


def available():
    return bool(config.QWEN_KEY)


def native_base():
    from .qwen_audio import native_base as base

    return base()


def _http(method, path, body=None, headers=None, timeout=120):
    h = {"Authorization": "Bearer " + (config.QWEN_KEY or ""), "Content-Type": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(native_base() + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise MediaError(_explain(e.code, e.read().decode("utf-8", "replace"))) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MediaError("Alibaba не отвечает ({})".format(getattr(e, "reason", e))) from None


def _explain(code, text):
    """Ответ сервера → понятная причина."""
    try:
        err = json.loads(text)
        msg = "{} {}".format(err.get("code", ""), err.get("message", "")).strip()
    except ValueError:
        msg = text[:200]
    low = msg.lower()
    if code == 429 and any(w in low for w in ("quota", "insufficient", "arrearage")):
        return "кредиты Qwen закончились"
    if "datainspection" in low or "inappropriate" in low or "green" in low:
        return "Alibaba отклонила описание как недопустимое — переформулируйте"
    if code in (401, 403):
        return "ключ Qwen не подходит для этой модели ({})".format(msg[:120])
    if "model" in low and ("not" in low or "support" in low or "exist" in low):
        return "модель недоступна в вашем тарифе ({})".format(msg[:120])
    return "Alibaba: HTTP {} {}".format(code, msg[:200])


def _slug(text):
    words = re.findall(r"\w+", text.lower())[:5]
    return "-".join(words)[:40] or "chloe"


def _save(url, folder, prompt, ext):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "{}-{}{}".format(time.strftime("%Y%m%d-%H%M%S"), _slug(prompt), ext)
    n = 1
    while path.exists():
        path = path.with_name("{}-{}{}".format(path.stem.rsplit("-", 1)[0] if n > 1 else path.stem, n, ext))
        n += 1
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        path.unlink(missing_ok=True)
        raise MediaError("не удалось скачать файл ({})".format(getattr(e, "reason", e))) from None
    return path


def as_data_uri(path):
    """Локальная картинка → data:…;base64 (модели Alibaba принимают её вместо ссылки)."""
    p = pathlib.Path(os.path.expanduser(str(path)))
    if not p.is_file():
        raise MediaError("нет файла {}".format(p))
    if p.stat().st_size > 10 * 1024 * 1024:
        raise MediaError("картинка больше 10 МБ")
    kind = mimetypes.guess_type(p.name)[0] or "image/png"
    return "data:{};base64,{}".format(kind, base64.b64encode(p.read_bytes()).decode())


def _image_ref(src):
    return src if re.match(r"^(https?://|data:)", src or "") else as_data_uri(src)


# --- картинки ---
def image(prompt, ratio="1:1", n=1, source=None, model=None):
    """Нарисовать (или изменить картинку source по описанию). Возвращает список сохранённых файлов."""
    if not prompt.strip():
        raise MediaError("нужно описание картинки")
    content = ([{"image": _image_ref(source)}] if source else []) + [{"text": prompt}]
    params = {"n": max(1, min(int(n or 1), 4)), "watermark": False}
    if not source:
        params["size"] = SIZES.get(ratio, ratio if re.match(r"^\d+\*\d+$", ratio or "") else SIZES["1:1"])
    body = {"model": model or IMAGE_MODEL, "input": {"messages": [{"role": "user", "content": content}]}, "parameters": params}
    out = _http("POST", "/api/v1/services/aigc/multimodal-generation/generation", body, timeout=180)
    urls = [c["image"] for ch in (out.get("output") or {}).get("choices", [])
            for c in (ch.get("message") or {}).get("content", []) if c.get("image")]
    if not urls:
        raise MediaError("Alibaba не вернула картинку ({})".format(json.dumps(out, ensure_ascii=False)[:200]))
    return [_save(u, IMAGE_DIR, prompt, ".png") for u in urls]


# --- видео ---
def video_start(prompt, source=None, seconds=5, resolution="720P", ratio="16:9", model=None):
    """Поставить видео в очередь. Возвращает id задачи."""
    if not prompt.strip() and not source:
        raise MediaError("нужно описание видео")
    inp = {"prompt": prompt}
    params = {"resolution": resolution, "duration": max(3, min(int(seconds or 5), 15)), "watermark": False}
    if source:
        inp["media"] = [{"type": "first_frame", "url": _image_ref(source)}]     # happyhorse i2v: старое поле img_url не принимается
    else:
        params["ratio"] = ratio
    body = {"model": model or (I2V_MODEL if source else VIDEO_MODEL), "input": inp, "parameters": params}
    out = _http("POST", "/api/v1/services/aigc/video-generation/video-synthesis", body,
                headers={"X-DashScope-Async": "enable"}, timeout=60)
    task = (out.get("output") or {}).get("task_id")
    if not task:
        raise MediaError("Alibaba не приняла задачу ({})".format(json.dumps(out, ensure_ascii=False)[:200]))
    return task


def video_status(task):
    """(status, video_url или None, причина ошибки или None). status: PENDING / RUNNING / SUCCEEDED / FAILED / …"""
    out = (_http("GET", "/api/v1/tasks/" + task, timeout=30).get("output") or {})
    status = out.get("task_status", "UNKNOWN")
    reason = None
    if status in ("FAILED", "CANCELED", "UNKNOWN"):
        reason = _explain(400, json.dumps({"code": out.get("code", status), "message": out.get("message", "")}))
    return status, out.get("video_url"), reason


def video_wait(task, prompt, poll=10, wait=VIDEO_WAIT, sleep=time.sleep):
    """Ждать готовое видео и скачать. Возвращает путь к файлу."""
    end = time.time() + wait
    while time.time() < end:
        status, url, reason = video_status(task)
        if status == "SUCCEEDED" and url:
            return _save(url, VIDEO_DIR, prompt, ".mp4")
        if reason:
            raise MediaError(reason)
        sleep(poll)
    raise MediaError("видео не готово за {} минут — задача {}".format(wait // 60, task))


def short(path):
    try:
        return "~/" + str(pathlib.Path(path).relative_to(HOME))
    except ValueError:
        return str(path)
