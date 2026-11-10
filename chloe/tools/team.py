"""Инструмент delegate — ядро Chloe поручает задачу агенту; agents — кто есть, что делают, отчёты."""
import time

from .. import agents as ag


def _announce(rid, status, report):
    from ..voice import voice

    name = ag.AGENTS[ag.runs.get(rid)["agent"]]["name"]
    first = report.strip().split("\n")[0][:240]
    text = "{} закончил: {}".format(name, first) if status == "готово" else "{} — {}.".format(name, report[:160])
    print("[агенты] " + text)
    voice.say(text + (" Полный отчёт — «покажи отчёт {}».".format(rid) if len(report) > len(first) + 20 else ""))


def tool_delegate(a):
    agent = ag.find(a.get("agent"))
    task = (a.get("task") or "").strip()
    if not agent:
        return "Нет такого агента. Есть: " + ", ".join("{} ({})".format(v["name"], k) for k, v in ag.AGENTS.items())
    if len(task) < 5:
        return "Нужна задача (task) — что агенту сделать."
    try:
        rid = ag.delegate(agent, task, announce=_announce)
    except ag.AgentError as e:
        return "Не могу: {}.".format(e)
    return ("Поручила {} (№{}): работает в фоне, когда закончит — расскажу. Можешь пока говорить со мной о другом."
            .format(ag.AGENTS[agent]["name"].lower(), rid))


def tool_agents(a):
    action = a.get("action", "list")
    if action == "list":
        lines = ["Мои агенты (я — координатор, поручаю им задачи):"]
        for k, v in ag.AGENTS.items():
            lines.append("• {} — {} (инструменты: {})".format(v["name"], v["brief"].split(". ")[0].replace("Ты — ", ""),
                                                              ", ".join(sorted(v["tools"]))))
        running = ag.runs.running()
        if running:
            lines.append("Сейчас работают: " + "; ".join("№{} {}: {}".format(r["id"], ag.AGENTS[r["agent"]]["name"], r["task"][:60]) for r in running))
        return "\n".join(lines)
    if action == "reports":
        rows = ag.runs.recent()
        if not rows:
            return "Агенты ещё ничего не делали."
        return "\n".join("№{} {} — {} ({}): {}".format(r["id"], ag.AGENTS.get(r["agent"], {}).get("name", r["agent"]), r["status"],
                                                      time.strftime("%d.%m %H:%M", time.localtime(r["started"])), r["task"][:80]) for r in rows)
    r = ag.runs.get(int(a.get("id") or 0))
    if not r:
        return "Нет такого отчёта."
    if action == "show":
        return "[Отчёт агента — по данным из его источников]\n№{} {} — {}. Задача: {}\nШагов: {}, инструменты: {}\n\n{}".format(
            r["id"], ag.AGENTS.get(r["agent"], {}).get("name", r["agent"]), r["status"], r["task"], r["steps"], r["tools"] or "—",
            r["report"] or "(ещё работает)")
    if action == "stop":
        return "Останавливаю агента №{}.".format(r["id"]) if ag.stop(r["id"]) else "Агент №{} уже не работает.".format(r["id"])
    return "Неизвестное действие: " + action
