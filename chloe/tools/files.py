"""Файлы и папки: найти, прочитать, записать, создать, переместить, скопировать, удалить в корзину."""
import os
import shutil

from ..changes import changes
from ..voice import confirm
from ..permissions import permissions
from .paths import P, PROTECTED, _target, is_sensitive, short


def replacing(dst, operation):
    """Выполняет operation(), а то, что лежало в dst, откладывает в копию — чтобы отмена могла вернуть.
    Если операция сорвалась, старое тут же возвращается на место. Возвращает путь копии или None."""
    backup = changes.set_aside(dst) if dst.exists() else None
    try:
        operation()
    except BaseException:
        if backup and not dst.exists():
            shutil.move(str(backup), str(dst))
        raise
    return backup


SKIP_DIRS = {"node_modules", "AppData", "Library", "__pycache__", "$Recycle.Bin", "proc", "sys"}


def tool_search_files(a):
    folder = P(a.get("folder") or "~")
    q = a["query"].lower()
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
                   and not permissions.in_vault(os.path.join(root, d))]   # в Private Vault не ищу
        for name in dirs + files:
            if q in name.lower():
                found.append(short(os.path.join(root, name)))
                if len(found) >= 40:
                    return "\n".join(found)
    return "\n".join(found) or "Ничего не найдено."


def tool_list_folder(a):
    p = P(a.get("path") or "~")
    if not p.is_dir():
        return "Это не папка: " + short(p)
    rows = []
    for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:200]:
        if e.is_dir():
            rows.append("[папка] " + e.name)
        else:
            try:
                rows.append("{}  ({} КБ)".format(e.name, max(1, e.stat().st_size // 1024)))
            except OSError:
                rows.append(e.name)
    return short(p) + ":\n" + ("\n".join(rows) or "(пусто)")


def tool_read_text_file(a):
    return P(a["path"]).read_text(encoding="utf-8", errors="replace")[:20000]


def tool_write_text_file(a):
    p = P(a["path"])
    if p.exists():
        if not confirm("Файл " + p.name + " уже есть. Перезаписать?"):
            return "Пользователь не разрешил перезапись."
    elif is_sensitive(p) and not confirm("Создать файл " + short(p) + "?"):
        return "Пользователь не разрешил создать файл."
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    backup = replacing(p, lambda: p.write_text(a["content"], encoding="utf-8"))
    changes.record("overwrite" if existed else "write_new", dst=p, backup=backup)
    return "Записано: " + short(p)


def tool_create_folder(a):
    p = P(a["path"])
    if p.is_dir():
        return "Папка уже есть: " + short(p)
    top = p   # самая верхняя из новых папок — её и убирает отмена
    while not top.parent.exists():
        top = top.parent
    p.mkdir(parents=True, exist_ok=True)
    changes.record("create_folder", dst=top)
    return "Папка готова: " + short(p)


def tool_move_path(a):
    src = P(a["source"])
    if not src.exists():
        return "Не найдено: " + short(src)
    dst = _target(src, a["destination"])
    if dst.exists() and not confirm(dst.name + " уже есть там. Заменить?"):
        return "Пользователь не разрешил замену."
    if not dst.exists() and is_sensitive(dst) and not confirm("Положить " + src.name + " в " + short(dst.parent) + "?"):
        return "Пользователь не разрешил."
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup = replacing(dst, lambda: shutil.move(str(src), str(dst)))
    changes.record("move", src=src, dst=dst, backup=backup)
    return "Перемещено: {} → {}".format(short(src), short(dst))


def tool_copy_path(a):
    src = P(a["source"])
    if not src.exists():
        return "Не найдено: " + short(src)
    dst = _target(src, a["destination"])
    if dst.exists() and not confirm(dst.name + " уже есть там. Заменить?"):
        return "Пользователь не разрешил замену."
    if not dst.exists() and is_sensitive(dst) and not confirm("Положить " + src.name + " в " + short(dst.parent) + "?"):
        return "Пользователь не разрешил."
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup = replacing(dst, lambda: shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst))
    changes.record("copy", src=src, dst=dst, backup=backup)
    return "Скопировано: {} → {}".format(short(src), short(dst))


def tool_delete_path(a):
    p = P(a["path"])
    if not p.exists():
        return "Не найдено: " + short(p)
    if p.resolve() in PROTECTED or len(p.resolve().parts) <= 2:
        return "Отказано: это важная системная или домашняя папка."
    what = ("папку " if p.is_dir() else "файл ") + p.name
    if p.is_dir():                              # сколько внутри — чтобы «да» было осознанным
        from ..sandbox import human, tree_size

        n, size = tree_size(p)
        what += " ({} файлов, {})".format("больше 20 000" if n > 20000 else n, human(size))
    if not confirm("Удалить " + what + " в корзину?"):
        return "Пользователь отменил удаление."
    try:
        from send2trash import send2trash

        send2trash(str(p))
        changes.record("delete", src=p.resolve())
        return "Перемещено в корзину: " + short(p)
    except ImportError:
        return "Не могу удалить безопасно: не установлен пакет send2trash."
