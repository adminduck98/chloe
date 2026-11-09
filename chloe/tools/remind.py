"""Напоминания и таймеры голосом."""
from ..reminders import due_from, reminders, when_text


def tool_set_reminder(a):
    if a.get("minutes") is None and not a.get("at"):
        return "Не найдено время: нужно minutes (через сколько минут) или at (например 18:30)."
    try:
        due = due_from(a.get("minutes"), a.get("at"))
    except ValueError as e:
        return "Не могу: " + str(e)
    rid = reminders.add(due, a.get("text") or "время вышло")
    return "Напоминание №{} на {}: {}.".format(rid, when_text(due), a.get("text") or "время вышло")


def tool_list_reminders(a):
    rows = reminders.pending()
    if not rows:
        return "Напоминаний нет."
    return "\n".join("[{}] {} — {}".format(r["id"], when_text(r["due"]), r["text"]) for r in rows)


def tool_cancel_reminder(a):
    if not reminders.cancel(int(a["id"])):
        return "Не найдено напоминание №{}.".format(a["id"])
    return "Отменила напоминание №{}.".format(a["id"])
