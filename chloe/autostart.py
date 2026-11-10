"""Запуск вместе с компьютером и защита от второй копии.

Автозапуск — обычный файл ~/.config/autostart/chloe.desktop (так запускают программы GNOME, Cinnamon, KDE, XFCE):
после входа в систему, через несколько секунд (чтобы поднялись звук и сеть), стартует start.sh.
Окна терминала нет, поэтому вывод пишется в ~/.chloe/chloe.log (прошлый запуск — chloe.log.1).
Включить: python run.py --autostart on, выключить: --autostart off.

Одна копия: файл-замок ~/.chloe/chloe.lock. Вторая Chloe (например, ./start.sh при уже работающем автозапуске)
сразу выходит — иначе обе слушали бы микрофон и отвечали хором.
"""
import os
import pathlib

from .config import DATA, HOME

PROJECT = pathlib.Path(__file__).resolve().parent.parent
DELAY = 10   # секунд после входа в систему


def desktop_file():
    return pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "autostart" / "chloe.desktop"


def entry():
    start = str(PROJECT / "start.sh").replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return "\n".join([
        "[Desktop Entry]", "Type=Application", "Name=Chloe", "Comment=Голосовой помощник Chloe",
        'Exec="{}" --log'.format(start.replace("%", "%%")), "Terminal=false",
        "X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-Delay={}".format(DELAY), ""])


def enabled():
    return desktop_file().is_file()


def enable():
    f = desktop_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(entry(), encoding="utf-8")
    return f


def disable():
    f = desktop_file()
    if f.is_file():
        f.unlink()
        return True
    return False


_lock = None   # файл держим открытым до конца работы: замок снимается сам, даже если Chloe упала


def single_instance(path=None):
    """True — мы единственная Chloe. False — другая уже работает."""
    global _lock
    try:
        import fcntl
    except ImportError:          # Windows: замка нет, как и раньше
        return True
    f = open(path or DATA / "chloe.lock", "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock = f
    return True
