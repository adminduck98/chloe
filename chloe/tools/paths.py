"""Пути пользователя и правила безопасности: что нельзя удалять, что подтверждать, что считать программой."""
import os
import pathlib

from ..config import DESKTOP, DOCUMENTS, DOWNLOADS, EXECUTABLE_EXT, HOME, OS_NAME


def P(path):
    """Путь пользователя: ~ раскрывается, относительный путь — от домашней папки."""
    p = pathlib.Path(os.path.expandvars(str(path))).expanduser()
    if not p.is_absolute():
        p = HOME / p
    return p


PROTECTED = {HOME, DESKTOP, DOCUMENTS, DOWNLOADS}
AUTOSTART_DIRS = (HOME / ".config" / "autostart", HOME / "Library" / "LaunchAgents",
                  HOME / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")


def is_executable(p):
    if p.suffix.lower() in EXECUTABLE_EXT:
        return True
    return OS_NAME != "Windows" and p.is_file() and os.access(p, os.X_OK)


def is_sensitive(p):
    """Программа, автозапуск, скрытые настройки или место вне домашней папки — запись туда подтверждается."""
    if p.suffix.lower() in EXECUTABLE_EXT:
        return True
    p = p.resolve()
    try:
        rel = p.relative_to(HOME)
    except ValueError:
        return True
    return any(part.startswith(".") for part in rel.parts) or any(d == p or d in p.parents for d in AUTOSTART_DIRS)


def short(p):
    try:
        return "~/" + str(pathlib.Path(p).relative_to(HOME))
    except ValueError:
        return str(p)


def _target(src, dst):
    dst = P(dst)
    return dst / src.name if dst.is_dir() else dst


def _unique(path):
    if not path.exists():
        return path
    stem, suf, i = path.stem, path.suffix, 2
    while True:
        cand = path.with_name("{} ({}){}".format(stem, i, suf))
        if not cand.exists():
            return cand
        i += 1
