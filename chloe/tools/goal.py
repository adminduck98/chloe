"""Инструмент goals — большие цели: цель → этапы → шаги, прогресс, что дальше."""
from ..goals import STATUS, STEP, GoalError, goals
from ..voice import confirm

MARK = {"todo": "○", "doing": "◐", "done": "●"}


def tree(g):
    head = "Цель №{} «{}» — {}, готово {}% ({} из {}){}{}".format(
        g["id"], g["title"], STATUS[g["status"]], g["progress"], g["done_n"], g["total_n"],
        ", срок {}".format(g["deadline"]) if g["deadline"] else "", ", проект «{}»".format(g["project"]) if g["project"] else "")
    lines = [head]
    if g["why"]:
        lines.append("  Зачем: " + g["why"])
    for st in g["stages"]:
        lines.append("  {} [{}] Этап: {} ({}/{})".format(MARK[st["status"]] if not st["steps"] else
                                                        ("●" if st["done_n"] == st["total_n"] else "◐" if st["done_n"] else "○"),
                                                        st["id"], st["title"], st["done_n"], st["total_n"]))
        for s in st["steps"]:
            lines.append("      {} [{}] {}{}".format(MARK[s["status"]], s["id"], s["title"], " (задача №{})".format(s["task_id"]) if s["task_id"] else ""))
    if g["next"]:
        lines.append("  Дальше: {} — {}".format(g["next"]["stage"], g["next"]["step"]) if g["next"]["stage"] != g["next"]["step"]
                     else "  Дальше: " + g["next"]["step"])
    return "\n".join(lines)


def _one(a):
    found = goals.find(a.get("id") or a.get("goal") or "")
    if not found:
        raise GoalError("нет такой цели (список — action=list)")
    if len(found) > 1:
        raise GoalError("нашла несколько: " + "; ".join("№{} «{}»".format(g["id"], g["title"]) for g in found))
    return found[0]


def tool_goals(a):
    action = a.get("action", "list")
    try:
        if action == "list":
            goals.sync_tasks()
            rows = goals.all(bool(a.get("all")))
            if not rows:
                return "Больших целей пока нет. Скажи цель — я предложу этапы и шаги, запишу после твоего согласия."
            return "\n".join("№{} «{}» — {}, {}%{}{}".format(g["id"], g["title"], STATUS[g["status"]], g["progress"],
                                                            ", срок " + g["deadline"] if g["deadline"] else "",
                                                            "; дальше: " + g["next"]["step"] if g["next"] else "") for g in rows)
        if action == "add":
            g = goals.add(a.get("title"), a.get("why"), a.get("project"), a.get("deadline"), a.get("stages") or [])
            return "Записала цель:\n" + tree(g)
        g = _one(a)
        if action == "show":
            goals.sync_tasks()
            return tree(goals.get(g["id"]))
        if action == "next":
            n = g["next"]
            return "По цели «{}» дальше: {}.".format(g["title"], n["step"] if n else "всё сделано") if n else \
                "Цель «{}»: все шаги сделаны.".format(g["title"])
        if action in ("step_done", "step_doing", "step_todo"):
            found = goals.find_step(g["id"], a.get("step") or "")
            if len(found) != 1:
                return "Какой шаг? " + ("; ".join("[{}] {}".format(s["id"], s["title"]) for s in found[:8]) if found else "не нашла такого")
            g = goals.set_step(found[0]["id"], action.split("_")[1])
            extra = " Цель достигнута!" if g["status"] == "done" else ""
            return "Отметила «{}» — {}. Цель «{}»: {}%.{}".format(found[0]["title"], STEP[action.split("_")[1]], g["title"], g["progress"], extra)
        if action == "step_add":
            stage = None
            if a.get("stage"):
                st = [s for s in goals.find_step(g["id"], a["stage"]) if s["parent_id"] is None]
                if len(st) != 1:
                    return "Какой этап? " + "; ".join("[{}] {}".format(s["id"], s["title"]) for s in g["stages"])
                stage = st[0]["id"]
            goals.add_step(g["id"], a.get("title") or a.get("step"), stage)
            return "Добавила. " + tree(goals.get(g["id"]))
        if action == "link_task":
            found = goals.find_step(g["id"], a.get("step") or "")
            if len(found) != 1 or not a.get("task_id"):
                return "Нужен шаг (step) и номер задачи проекта (task_id)."
            goals.link_task(found[0]["id"], int(a["task_id"]))
            return "Связала шаг «{}» с задачей №{}: сделаешь задачу — шаг отметится сам.".format(found[0]["title"], a["task_id"])
        if action == "edit":
            g = goals.edit(g["id"], title=a.get("title"), why=a.get("why"), project=a.get("project"), deadline=a.get("deadline"))
            return "Исправила:\n" + tree(g)
        if action in ("pause", "resume", "done", "drop"):
            status = {"pause": "paused", "resume": "active", "done": "done", "drop": "dropped"}[action]
            if action == "drop" and not confirm("Отменить цель «{}»?".format(g["title"])):
                return "Оставила цель."
            g = goals.set_status(g["id"], status)
            return "Цель «{}» — {}.".format(g["title"], STATUS[status])
        if action == "delete":
            if not confirm("Удалить цель «{}» со всеми этапами?".format(g["title"])):
                return "Оставила."
            goals.delete(g["id"])
            return "Удалила цель «{}».".format(g["title"])
    except GoalError as e:
        return "Не могу: {}.".format(e)
    return "Неизвестное действие: " + action
