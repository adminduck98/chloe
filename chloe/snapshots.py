"""Резервные копии мозга, памяти, напоминаний и журнала: раз в день и перед каждым стиранием, хранятся 14 дней.
Три самые свежие копии дня не удаляются никогда — даже если часы или ошибка сочтут их старыми.

~/.chloe/snapshots/2026-11-05/brain.json, memory.json, chloe.db, skills/ — какими они были в начале дня.
~/.chloe/snapshots/2026-11-05-1430-перед-сбросом/… — перед «Сбросить мозг» и перед восстановлением.
Вернуть: python run.py --restore [ДЕНЬ] (без дня — список копий). Делать при закрытой Chloe: иначе окно сохранит своё.
"""
import json
import re
import shutil
import sqlite3
import time

from .config import BRAIN_FILE, DATA, JOURNAL_FILE, MEMORY_FILE

SNAP_DIR = DATA / "snapshots"
KEEP_DAYS = 14
KEEP_LATEST = 3                 # столько последних копий дня остаётся всегда
FILES = (BRAIN_FILE, MEMORY_FILE, DATA / "permissions.json")   # карта прав и Private Vault — тоже
SKILLS_DIR = DATA / "skills"    # навыки, которым пользователь научил Chloe
DAY = re.compile(r"\d{4}-\d{2}-\d{2}$")


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
    if copy_db(JOURNAL_FILE, target / JOURNAL_FILE.name):
        saved.append(JOURNAL_FILE.name)
    if SKILLS_DIR.is_dir() and any(SKILLS_DIR.iterdir()):
        shutil.copytree(SKILLS_DIR, target / "skills", dirs_exist_ok=True)
        saved.append("skills")
    if not saved:
        target.rmdir()
    return saved


def copy_db(src, dst):
    """Напоминания, журнал и история изменений. Через sqlite backup — копия целая, даже если Chloe сейчас пишет в базу."""
    if not src.exists():
        return False
    try:
        with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
            a.backup(b)
        return True
    except sqlite3.Error as e:
        print("[копия базы не удалась: " + str(e)[:80] + "]")
        dst.unlink(missing_ok=True)
        return False


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
    latest = sorted((d.name for d in SNAP_DIR.iterdir() if d.is_dir() and DAY.match(d.name)), reverse=True)[:KEEP_LATEST]
    for d in SNAP_DIR.iterdir():
        m = re.match(r"(\d{4}-\d{2}-\d{2})", d.name)
        if d.is_dir() and m and m.group(1) < limit and d.name not in latest:
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
    if (src / JOURNAL_FILE.name).exists() and copy_db(src / JOURNAL_FILE.name, JOURNAL_FILE):
        back.append(JOURNAL_FILE.name)
    if (src / "skills").is_dir():
        shutil.copytree(src / "skills", SKILLS_DIR, dirs_exist_ok=True)
        back.append("skills")
    return back
