"""Инструмент workflows — автоматизации: по расписанию, на новый файл в папке, на новое сообщение в Telegram."""
import time

from ..voice import confirm
from ..workflows import KINDS, WorkflowError, workflows


def _t(ts):
    if not ts:
        return "—"
    d = time.localtime(ts)
    return time.strftime("%d.%m %H:%M", d)


def describe(w):
    return "№{} «{}» — {}{}: {} (запусков {}, последний {}{})".format(
        w["id"], w["name"], w["when"], "" if w["enabled"] else " [на паузе]", w["instruction"][:140], w["runs"], _t(w["last_run"]),
        ", следующий {}".format(_t(w["next_run"])) if w["enabled"] and w["next_run"] else "")


def tool_workflows(a):
    action = a.get("action", "list")
    try:
        if action == "list":
            rows = workflows.all()
            if not rows:
                return "Автоматизаций пока нет. Пример: «каждый понедельник в 9 утра — расскажи, что по проекту и какие задачи важные»."
            return "\n".join(describe(w) for w in rows)
        if action == "add":
            kind = a.get("when") or "schedule"
            spec = {"at": a.get("at"), "days": a.get("days"), "every_minutes": a.get("every_minutes"), "path": a.get("folder"),
                    "chat": a.get("chat")}
            w = workflows.add(a.get("name"), a.get("instruction"), kind, spec)
            return ("Создала автоматизацию " + describe(w) + ". Всё, что меняет данные или уходит наружу, она будет спрашивать "
                    "«да/нет», как и я. Пауза — «приостанови автоматизацию {}».".format(w["id"]))
        if action == "history":
            rows = workflows.runs()
            if not rows:
                return "Автоматизации ещё не запускались."
            return "\n".join("{} — «{}»: {}".format(_t(r["ts"]), r["name"] or "удалена", r["why"]) for r in rows)
        found = workflows.find(a.get("id") or a.get("name") or "")
        if not found:
            return "Такой автоматизации нет. Список — action=list."
        if len(found) > 1:
            return "Нашла несколько — какую? " + "; ".join("№{} «{}»".format(w["id"], w["name"]) for w in found)
        w = found[0]
        if action == "pause":
            workflows.set_enabled(w["id"], False)
            return "Приостановила «{}».".format(w["name"])
        if action == "resume":
            w = workflows.set_enabled(w["id"], True)
            return "Снова работает: " + describe(w)
        if action == "delete":
            if not confirm("Удалить автоматизацию «{}»?".format(w["name"])):
                return "Оставила."
            workflows.delete(w["id"])
            return "Удалила автоматизацию «{}».".format(w["name"])
        if action == "run":
            from ..signals import Typed, commands
            from ..workflows import request_text

            workflows.mark_run(w, "вручную")
            commands.put(Typed(request_text(w, "запуск вручную", ""), "local"))
            return "Запускаю «{}» сразу после этого ответа.".format(w["name"])
    except WorkflowError as e:
        return "Не могу: {}.".format(e)
    return "Неизвестное действие: " + action


assert set(KINDS) == {"schedule", "folder", "telegram"}
