"""Резервные копии мозга и памяти: раз в день и перед каждым стиранием, хранятся 7 дней.

~/.chloe/snapshots/2026-11-05/brain.json, memory.json — какими они были в начале дня.
~/.chloe/snapshots/2026-11-05-1430-перед-сбросом/… — перед «Сбросить мозг» и перед восстановлением.
Вернуть: python run.py --restore [ДЕНЬ] (без дня — список копий). Делать при закрытой Chloe: иначе окно сохранит своё.
"""
import json
import re
import shutil
import time

from .config import BRAIN_FILE, DATA, MEMORY_FILE

SNAP_DIR = DATA / "snapshots"
KEEP_DAYS = 7
FILES = (BRAIN_FILE, MEMORY_FILE)


def valid_json(path):
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, ValueError):
        return False


def snapshot(name):
    """Копия мозга и памяти в папку name. Битые файлы не копируются — копия хорошего важнее."""
    target = SNAP_DIR / name
    target.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in FILES:
        if f.exists() and valid_json(f):
            shutil.copy2(f, target / f.name)
            saved.append(f.name)
    if not saved:
        target.rmdir()
    return saved


def daily():
    """Копия дня, если сегодня её ещё нет; старше KEEP_DAYS — убираются."""
    today = time.strftime("%Y-%m-%d")
    if not (SNAP_DIR / today).exists():
        snapshot(today)
    prune()


def before(what):
    return snapshot(time.strftime("%Y-%m-%d-%H%M-") + what)


def prune(days=KEEP_DAYS):
    if not SNAP_DIR.exists():
        return
    limit = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    for d in SNAP_DIR.iterdir():
        m = re.match(r"(\d{4}-\d{2}-\d{2})", d.name)
        if d.is_dir() and m and m.group(1) < limit:
            shutil.rmtree(d, ignore_errors=True)


def days():
    return sorted((d.name for d in SNAP_DIR.iterdir() if d.is_dir()), reverse=True) if SNAP_DIR.exists() else []


def restore(name):
    """Возвращает мозг и память из копии; текущие сначала сохраняются как «перед-восстановлением»."""
    src = SNAP_DIR / name
    if not src.is_dir():
        raise ValueError("Нет копии «{}». Есть: {}".format(name, ", ".join(days()) or "ни одной"))
    before("перед-восстановлением")
    back = []
    for f in FILES:
        if (src / f.name).exists():
            shutil.copy2(src / f.name, f)
            back.append(f.name)
    return back
