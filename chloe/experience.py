"""Мозг как карта реального опыта: что из мира пользователя Chloe трогала и что из памяти ей пригодилось.

things_of — из шага инструмента достаёт предметы: программу, сайт, папку, файл, место, человека.
Каждый становится нейроном в мозге (один раз) и связывается с навыком, которым Chloe его использовала.

recalled — какие воспоминания реально пригодились: их слова есть в том, что Chloe сделала или ответила,
но этих слов не было в просьбе пользователя — значит, взяла из памяти.
"""
import pathlib
import re
import urllib.parse

from .config import HOME

ZONES = {   # вид предмета → зона мозга (зоны появляются сами, когда появляется первый такой предмет)
    "Программа": "Программы", "Сайт": "Сайты", "Папка": "Папки", "Файл": "Папки",
    "Место": "Места", "Человек": "Люди",
}


def short(p):
    p = pathlib.Path(p).expanduser()
    try:
        return "~/" + str(p.relative_to(HOME)) if p != HOME else "~"
    except ValueError:
        return str(p)


def thing(kind, name, q=None):
    name = name[:40]
    return {"kind": kind, "name": name, "zone": topic_of(name) or ZONES[kind], "q": q or name, "desc": kind}


def topic_of(name):
    """Тема, в которую сон положил этот предмет (зоны по смыслу, topics.py), или None."""
    from .settings import settings

    key = "w:" + name
    for topic, keys in (settings.get("topics") or {}).items():
        if key in keys:
            return topic
    return None


def site(url):
    host = urllib.parse.urlparse(url if "//" in url else "https://" + url).hostname or ""
    host = host[4:] if host.startswith("www.") else host
    return thing("Сайт", host) if host else None


def folder(path, is_file=None):
    """Папка, где Chloe работала; для файла — его папка."""
    p = pathlib.Path(str(path)).expanduser()
    if is_file is None:
        is_file = p.suffix != "" and not p.is_dir()
    d = p.parent if is_file else p
    return thing("Папка", short(d), str(d))


FILE_TOOLS = {"write_text_file": "path", "read_text_file": "path", "delete_path": "path", "open_path": "path"}


def things_of(name, args, ok=True):
    """Предметы из мира пользователя, которые трогал этот шаг."""
    if not ok or not isinstance(args, dict):
        return []
    out = []
    try:
        if name == "open_app" and args.get("name"):
            out.append(thing("Программа", str(args["name"]).strip().capitalize()))
        elif name in ("open_url", "read_web_page", "download_file") and args.get("url"):
            out.append(site(args["url"]))
            if name == "download_file":
                out.append(folder(args.get("folder") or _downloads(), is_file=False))
        elif name in FILE_TOOLS and args.get("path"):
            out.append(folder(args["path"]))
            if name in ("read_text_file", "open_path") and pathlib.Path(str(args["path"])).suffix:
                p = pathlib.Path(str(args["path"])).expanduser()
                out.append(thing("Файл", p.name, str(p)))
        elif name in ("move_path", "copy_path"):
            out += [folder(args.get("source", "")), folder(args.get("destination", ""))]
        elif name in ("create_folder", "list_folder") and args.get("path"):
            out.append(folder(args["path"], is_file=False))
        elif name == "search_files" and args.get("folder"):
            out.append(folder(args["folder"], is_file=False))
        elif name == "window" and args.get("name"):
            out.append(thing("Программа", str(args["name"]).strip().capitalize()))
        elif name in ("weather", "set_city") and args.get("city"):
            out.append(thing("Место", str(args["city"]).split(",")[0].strip().capitalize()))
        elif name in ("tg_read", "tg_send") and args.get("chat"):
            out.append(thing("Человек", str(args["chat"]).strip(), str(args["chat"]).strip()))
    except Exception:
        return []
    seen, uniq = set(), []
    for t in out:
        if t and t["name"] and t["name"] not in seen:
            seen.add(t["name"])
            uniq.append(t)
    return uniq


def _downloads():
    from .config import DOWNLOADS

    return DOWNLOADS


STOP = {"который", "которая", "которые", "чтобы", "когда", "очень", "любит", "любимый", "любимая", "пользователь",
        "зовут", "живёт", "живет", "работает", "считает", "нравится", "может", "своей", "своего", "всегда", "часто"}


def stems(text):
    """Значимые слова: первые 5 букв (Мадина, Мадине → мадин), слова от 5 букв, без служебных."""
    return {w[:5] for w in re.findall(r"[a-zа-яё0-9]+", text.lower()) if len(w) >= 5 and w not in STOP}


def recalled(user_text, used_text, items):
    """Воспоминания, слова которых есть в сделанном/сказанном, но не в просьбе."""
    asked, used = stems(user_text), stems(used_text)
    out = []
    for m in items:
        key = stems(m["text"]) - asked
        if key and key & used:
            out.append(m["text"])
    return out
