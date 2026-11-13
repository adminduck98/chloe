"""Инструмент youtube: статистика канала (только чтение), пакет к публикации для любого видео, открыть загрузку в Studio."""
import os
import pathlib
import threading
import webbrowser

from .. import youtube_api as yt

_signing = threading.Event()
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")


def _connect():
    from ..voice import voice

    try:
        yt.sign_in()
        voice.say("YouTube подключён: вижу статистику канала, менять ничего не могу.")
    except Exception as e:
        voice.say("YouTube не подключён: {}.".format(str(e).rstrip(".")))
    finally:
        _signing.clear()


def _status():
    if yt.connected():
        return "YouTube подключён (только чтение: статистика и список роликов)."
    if not yt.client():
        return ("YouTube не подключён: нет файла ~/.config/chloe/google_client.json. Пользователю нужно создать OAuth client "
                "(тип Desktop app) в Google Cloud Console, сохранить файл туда и включить YouTube Data API v3 и "
                "YouTube Analytics API.")
    return ("YouTube не подключён. Клиент Google есть (тот же, что у календаря). Перед входом в Google Cloud Console у этого "
            "проекта нужно включить «YouTube Data API v3» и «YouTube Analytics API» (APIs & Services → Library); "
            "дальше — action=connect.")


def _video_path(a):
    raw = str(a.get("path") or "").strip()
    if not raw:
        return None
    p = pathlib.Path(os.path.expanduser(raw)).resolve()
    return p if p.is_file() and p.suffix.lower() in VIDEO_EXT else None


def _package(a):
    from .. import publish
    from . import media

    path = _video_path(a)
    if not path:
        return "Нужен путь к видео (path): mp4, mov, mkv или webm."
    topic = str(a.get("topic") or "").strip()
    holder = {}

    def progress(text):
        job = media.jobs.get(holder.get("id"))
        if job:
            job["step"] = str(text)

    def work():
        out, report = publish.package_video(path, topic, lang=a.get("lang") or None, progress=progress)
        print("[публикация] " + "; ".join(report))
        return [out]
    holder["id"] = media._start("publish", path.name, work, a.get("open", True) is not False)
    return ("Готовлю «{}» к публикации (#{}): слушаю речь, пишу название, описание с главами и теги, делаю 3 обложки. "
            "Длинный ролик — несколько минут. Папка будет рядом с видео: «{} — к публикации». Скажу, когда готово."
            .format(path.name, holder["id"], path.stem))


def _upload(a):
    from .. import publish
    from . import media

    path = _video_path(a)
    folder = path.with_name(path.stem + " — " + publish.FOLDER) if path else None
    webbrowser.open(yt.STUDIO_UPLOAD)
    if folder and folder.is_dir():
        media.show(folder)
    hint = ("Открыла папку пакета: обложки и описание.txt — оттуда." if folder and folder.is_dir()
            else "Пакета к публикации для этого видео нет — могу сделать (action=package)." if path else "")
    return ("Открыла загрузку в YouTube Studio. Видео перетаскивает и публикует пользователь сам — ролики, загруженные "
            "через непроверенное приложение, YouTube навсегда оставляет закрытыми. " + hint).strip()


def tool_youtube(a):
    action = a.get("action") or "stats"
    if action == "status":
        return _status()
    if action == "connect":
        if yt.connected():
            return "YouTube уже подключён."
        if not yt.client():
            return _status()
        if _signing.is_set():
            return "Страница входа Google уже открыта — жду, пока пользователь войдёт."
        _signing.set()
        threading.Thread(target=_connect, daemon=True).start()
        return ("Открыла страницу входа Google. Пользователь сам выбирает аккаунт с каналом и нажимает «Разрешить» "
                "(доступ только на чтение); пароль я не вижу. Если Google пишет «приложение не проверено» — это наше "
                "собственное приложение: «Дополнительно» → «Перейти». Когда закончит, скажу «YouTube подключён».")
    if action == "disconnect":
        return "Доступ к YouTube отозван у Google, токен удалён." if yt.sign_out() else "YouTube и так не был подключён."
    if action == "package":
        return _package(a)
    if action == "upload":
        return _upload(a)
    if action in ("stats", "videos"):
        if not yt.connected():
            return _status()
        try:
            if action == "videos":
                return yt.describe_videos(yt.recent(int(a.get("limit") or 10)))
            return yt.describe_stats(yt.stats(max(7, min(365, int(a.get("days") or 28)))))
        except (yt.YouTubeError, yt.NotConnected) as e:
            return "Не получилось: {}.".format(str(e).rstrip("."))
    return "Действия: stats, videos, package, upload, status, connect, disconnect."
