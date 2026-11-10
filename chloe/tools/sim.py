"""Инструмент simulate — «что будет, если…»: разбор и проба плана до настоящих действий."""
from .. import sandbox as sb


def tool_simulate(a):
    steps = a.get("steps") or ([{"tool": "run_command", "args": {"command": a["command"]}}] if a.get("command") else [])
    if not steps:
        return "Нужен command (команда терминала) или steps — список шагов плана: [{tool, args}, …]."
    from ..permissions import permissions

    lines, worst, undo = [], "low", True
    for i, step in enumerate(steps[:12], 1):
        tool = step.get("tool") or ""
        args = step.get("args") or {}
        verdict = permissions.check(tool, args)
        if verdict and verdict[0] == "block":
            lines.append("{}. {} — запрещено: {}.".format(i, tool, verdict[1]))
            continue
        if tool == "run_command":
            from .system import clean_command, starts_chloe

            cmd = clean_command(str(args.get("command", "")))
            if starts_chloe(cmd):
                lines.append("{}. run_command — не выполню: это запуск второй Chloe.".format(i))
                continue
            info = sb.preview_command(cmd)
            title = "{}. команда «{}»".format(i, cmd[:80])
        else:
            info = sb.analyse(tool, args)
            title = "{}. {}".format(i, info["what"] if info["what"] != tool else tool)
        if sb.ORDER[info["risk"]] > sb.ORDER[worst]:
            worst = info["risk"]
        undo = undo and info["reversible"]
        lines.append(sb.report(info, title))
    head = "Проверка плана (ничего не выполнено): общий риск {}, {}.".format(
        sb.RISK[worst], "всё можно отменить" if undo else "есть шаги, которые отменить нельзя")
    tail = ("Проба показывает след только в домашней папке; сеть, устройства и чужие сервисы она не проверяет. "
            "Расскажи пользователю коротко: что изменится, чем рискуем, и предложи более безопасный путь, если он есть "
            "(корзина вместо rm, копия перед правкой).")
    return head + "\n" + "\n".join(lines) + "\n" + tail
