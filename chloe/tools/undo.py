"""Отмена изменений файлов голосом: «Хлоя, отмени последнее», «верни файл, который ты переместила»."""
from ..changes import changes
from ..voice import confirm


def tool_list_changes(a):
    rows = [c for c in changes.list(int(a.get("count") or 10))]
    if not rows:
        return "Пока никаких изменений файлов не было."
    return "\n".join("[{}] {}{}".format(c["id"], c["text"], " (уже отменено)" if c["undone"] else "") for c in rows)


def tool_undo_change(a):
    row = changes.get(int(a["id"])) if a.get("id") else changes.last_open()
    if row is None:
        return "Нечего отменять."
    if not confirm("Отменить: " + changes.describe(row) + "?"):
        return "Пользователь не разрешил отмену."
    ok, message = changes.undo(row["id"], by="голос")
    return message
