"""Студия: доска серий канала — идея → сценарий → проба → ролик → пакет → Shorts → вышло.

Сама ничего не производит: читает папки проектов студии (~/Видео/Chloe/проекты/*/project.json, их делает
make_film) и запускает те же шаги, что и голосом («делай весь ролик», «сделай шортсы»), — через run_tool,
с теми же подтверждениями цены, бюджетом пакета Qwen и журналом. Вопрос «да/нет» о цене приходит голосом
и во «Входящие».

Своё хранит только:
  • идеи серий — ~/.chloe/studio_ideas.json (их пишет владелец в окне или Chloe инструментом episodes);
  • отметку «вышло» — board.json в папке проекта (дата и ссылка; загружает в YouTube Studio сам владелец:
    ролики, загруженные через API непроверенного приложения, YouTube оставляет закрытыми).
"""
import base64
import io
import json
import pathlib
import threading
import time

from .config import DATA

IDEAS_FILE = DATA / "studio_ideas.json"
STAGES = ("idea", "script", "preview", "film", "package", "shorts", "published")
STAGE_RU = {"script": "сценарий", "preview": "проба", "film": "ролик", "package": "пакет", "shorts": "Shorts", "published": "вышло"}
MODES_RU = {"anim": "мультфильм", "slides": "слайды", "live": "живое видео", "director": "раскадровка"}
_lock = threading.Lock()
_thumbs = {}
_channel = {"at": 0, "data": None}


# ---------------------------------------------------------------- идеи
def ideas():
    try:
        items = json.loads(IDEAS_FILE.read_text(encoding="utf-8"))
        return [i for i in items if isinstance(i, dict) and i.get("text")]
    except (OSError, ValueError):
        return []


def _save_ideas(items):
    IDEAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = IDEAS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(IDEAS_FILE)


def add_idea(text, source="владелец", why=""):
    text = str(text or "").strip()[:500]
    if not text:
        return None
    with _lock:
        items = ideas()
        if any(i["text"].lower() == text.lower() for i in items):
            return next(i for i in items if i["text"].lower() == text.lower())
        item = {"id": max([i.get("id", 0) for i in items] + [0]) + 1, "text": text, "source": source,
                "why": str(why or "")[:300], "ts": time.time()}
        items.append(item)
        _save_ideas(items)
    _notify()
    return item


def remove_idea(iid):
    with _lock:
        items = ideas()
        left = [i for i in items if i.get("id") != int(iid)]
        _save_ideas(left)
    _notify()
    return len(left) < len(items)


def _notify():
    try:
        from .brain import brain

        brain.js("chloeStudio")
    except Exception:
        pass


# ---------------------------------------------------------------- серии
def _projects_dir():
    from .studio import PROJECTS

    return PROJECTS


def _board(folder):
    try:
        return json.loads((folder / "board.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _set_board(folder, **kw):
    data = dict(_board(folder), **kw)
    (folder / "board.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def _running():
    """Фоновые работы студии: название → «готово сцен: 2 из 4»."""
    try:
        from .tools.media import jobs
    except Exception:
        return {}
    out = {}
    for j in jobs.values():
        if j["state"] == "работаю" and j["kind"] in ("preview", "film", "shorts"):
            out[j["prompt"]] = {"kind": j["kind"], "step": j.get("step") or "работаю", "since": j["started"]}
    return out


def episode(folder, running=None):
    from .publish import FOLDER

    folder = pathlib.Path(folder)
    try:
        p = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scenes = p.get("scenes") or []
    clips = [c for c in folder.glob("clip*.mp4") if not c.name.endswith(".part.mp4")]
    pub = folder / FOLDER
    films = sorted(pub.glob("*.mp4")) if pub.is_dir() else []
    covers = sorted(pub.glob("обложка-*.jpg")) if pub.is_dir() else []
    has_text = (pub / "описание.txt").exists()
    shorts = sorted((pub / "shorts").glob("short-*.mp4")) if (pub / "shorts").is_dir() else []
    board = _board(folder)
    if board.get("published"):
        stage = "published"
    elif shorts:
        stage = "shorts"
    elif films and (covers or has_text):
        stage = "package"
    elif films or (scenes and len(clips) >= len(scenes)):
        stage = "film"
    elif clips:
        stage = "preview"
    else:
        stage = "script"
    script = p.get("script") or {}
    title = p.get("title") or script.get("title") or folder.name
    job = (running if running is not None else _running()).get(title)
    cost = 0.0
    if stage in ("script", "preview") and p.get("mode") in ("live", "slides"):
        try:
            from .studio import estimate

            cost = round(estimate(scenes[len(clips):], p.get("mode"), p.get("look")), 1)
        except Exception:
            cost = 0.0
    return {"folder": str(folder), "title": title, "logline": script.get("logline", ""), "mode": p.get("mode", "slides"),
            "mode_ru": MODES_RU.get(p.get("mode"), p.get("mode", "")), "ratio": p.get("ratio", "16:9"), "created": p.get("created") or folder.stat().st_mtime,
            "scenes": len(scenes), "clips": min(len(clips), len(scenes)), "stage": stage, "stage_ru": STAGE_RU[stage],
            "video": str(films[-1]) if films else "", "covers": len(covers), "shorts": len(shorts), "text": has_text,
            "published": board.get("published"), "link": board.get("link", ""), "job": job, "cost_rest": cost,
            "narration": [s.get("narration", "") for s in scenes][:12]}


def episodes(limit=40):
    root = _projects_dir()
    if not root.exists():
        return []
    running = _running()
    out = [e for e in (episode(f.parent, running) for f in sorted(root.glob("*/project.json"), reverse=True)[:limit]) if e]
    out.sort(key=lambda e: (e["stage"] == "published", -(e["created"] or 0)))
    return out


def _own(folder):
    """Папка — действительно проект студии (окно не может попросить действие над чужой папкой)."""
    root = _projects_dir().resolve()
    p = pathlib.Path(folder).resolve()
    return p.parent == root and (p / "project.json").exists()


def cover(folder, n=1, width=360):
    """Маленькая обложка серии (JPEG base64) — для карточки в окне. Кэш по времени файла."""
    from .publish import FOLDER

    if not _own(folder):
        return ""
    path = pathlib.Path(folder) / FOLDER / "обложка-{}.jpg".format(int(n))
    try:
        mt = path.stat().st_mtime
    except OSError:
        return ""
    key = (str(path), width)
    if key in _thumbs and _thumbs[key][0] == mt:
        return _thumbs[key][1]
    try:
        from PIL import Image

        im = Image.open(path)
        im.thumbnail((width, width))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=80)
        data = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""
    _thumbs[key] = (mt, data)
    return data


def action(folder, what, arg=""):
    """Шаг конвейера из окна. Долгие — в фоне через run_tool (те же подтверждения цены и бюджет)."""
    from .publish import FOLDER

    if not _own(folder):
        return {"error": "это не проект студии"}
    folder = pathlib.Path(folder)
    ep = episode(folder) or {}
    if what in ("continue", "shorts"):
        if ep.get("job"):
            return {"error": "уже идёт: " + ep["job"]["step"]}
        from .tools import run_tool

        args = {"action": what, "project": str(folder), "open": False}
        threading.Thread(target=run_tool, args=("make_film", args), daemon=True, name="studio-" + what).start()
        return {"ok": True, "message": {"continue": "Доделываю ролик", "shorts": "Режу Shorts"}[what] + " «{}»".format(ep.get("title", ""))}
    if what == "publish_pack":          # пакет вручную (если при сборке ролика он не вышел)
        if not ep.get("video"):
            return {"error": "ролик ещё не готов целиком"}
        def work():
            from . import publish, studio

            p = studio.load_project(folder)
            script = dict(p.get("script") or {}, scenes=p["scenes"])
            script.setdefault("title", p["title"])
            publish.package(folder, ep["video"], script, p.get("mode", "slides"), p.get("look"), p.get("ratio", "16:9"))
            _notify()
        threading.Thread(target=work, daemon=True, name="studio-pack").start()
        return {"ok": True, "message": "Собираю пакет к публикации"}
    if what == "open_folder":
        return _open(folder / FOLDER if (folder / FOLDER).is_dir() else folder)
    if what == "open_video":
        return _open(pathlib.Path(ep["video"])) if ep.get("video") else {"error": "ролика ещё нет"}
    if what == "open_text":
        return _open(folder / FOLDER / "описание.txt") if ep.get("text") else {"error": "описания ещё нет"}
    if what == "upload":                # загрузка — руками в YouTube Studio: открыть её и папку с пакетом
        from .tools.system import tool_open_url
        from .youtube_api import STUDIO_UPLOAD

        tool_open_url({"url": STUDIO_UPLOAD})
        _open(folder / FOLDER if (folder / FOLDER).is_dir() else folder)
        return {"ok": True, "message": "Открыла YouTube Studio и папку с пакетом. Загрузите ролик и нажмите «вышло»."}
    if what == "published":
        link = str(arg or "").strip()[:300]
        _set_board(folder, published=time.time(), link=link)
        _journal("Серия вышла: «{}»{}".format(ep.get("title", ""), " — " + link if link else ""))
        _notify()
        return {"ok": True}
    if what == "unpublished":
        _set_board(folder, published=None)
        _notify()
        return {"ok": True}
    return {"error": "не знаю такого шага: " + str(what)}


def _open(path):
    from .tools.system import tool_open_path

    return {"ok": True, "message": tool_open_path({"path": str(path)})}


def _journal(text):
    try:
        from .journal import journal

        journal.add("tool", "Студия", text, {"by": "окно"})
    except Exception:
        pass


# ---------------------------------------------------------------- канал и бюджет
def channel(fresh=False):
    """Коротко о канале (кэш 10 минут; YouTube не подключён — None) и сколько пакета Qwen ушло за месяц."""
    out = {"budget": None, "week_videos": None, "week_limit": None, "youtube": None, "youtube_error": ""}
    try:
        from . import media_budget as MB

        out.update(budget=round(MB.month_percent(), 1), week_videos=MB.week_videos(), week_limit=MB.WEEKLY_VIDEOS)
    except Exception:
        pass
    try:
        from . import youtube_api as yt

        if not yt.connected():
            out["youtube_error"] = "YouTube не подключён — скажите: «Хлоя, подключи YouTube»"
            return out
        if fresh or time.time() - _channel["at"] > 600 or not _channel["data"]:
            s = yt.stats(28)
            now, before = s.get("now") or {}, s.get("before") or {}
            _channel.update(at=time.time(), data={
                "title": s["channel"]["title"], "subscribers": s["channel"]["subscribers"], "videos": s["channel"]["videos"],
                "views28": int(now.get("views") or 0), "views28_before": int(before.get("views") or 0),
                "subs28": int(now.get("subscribersGained") or 0) - int(now.get("subscribersLost") or 0),
                "top": [{"title": r.get("title", ""), "views": int(r.get("views") or 0),
                         "percent": round(r.get("averageViewPercentage") or 0)} for r in (s.get("top") or [])[:3]]})
        out["youtube"] = _channel["data"]
    except Exception as e:
        out["youtube_error"] = "статистика YouTube не загрузилась: " + str(e)[:120]
    return out


def make_from_idea(iid, mode="anim", ratio="9:16", duration=20):
    """Идея → сценарий и проба (make_film с idea). Мультфильм — бесплатно и сразу; слайды и живое — с вопросом о цене."""
    item = next((i for i in ideas() if i.get("id") == int(iid)), None)
    if not item:
        return {"error": "нет такой идеи"}
    mode = mode if mode in ("anim", "slides", "live", "director") else "anim"
    ratio = ratio if ratio in ("9:16", "16:9", "1:1") else "9:16"
    args = {"idea": item["text"], "notes": item.get("why", ""), "mode": mode, "ratio": ratio,
            "duration": max(10, min(600, int(duration or 20))), "open": False}

    def work():
        from .tools import run_tool

        out = run_tool("make_film", args)
        if mode != "director" and isinstance(out, str) and out.startswith("Нач"):
            remove_idea(item["id"])            # серия началась — идея стала карточкой на доске
        _notify()
    threading.Thread(target=work, daemon=True, name="studio-make").start()
    return {"ok": True, "message": "Пишу сценарий «{}» — около двух минут".format(item["text"][:60])}
