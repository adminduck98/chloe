"""Инструмент mission — задания из нескольких шагов, которые живут между перезапусками (см. chloe/missions.py)."""
from .. import missions as ms
from ..voice import confirm


def _pick(a):
    m = ms.missions.find(a.get("id") or a.get("mission"))
    if not m:
        raise ms.MissionError("нет такого незаконченного задания")
    return m


def tool_mission(a):
    action = a.get("action", "list")
    try:
        if action == "plan":
            m = ms.missions.create(a.get("title"), a.get("steps"), a.get("request") or "")
            if ms.missions.active():
                return ("План записан как задание №{} ({} шагов), но сейчас идёт другое задание — начну это, когда скажете "
                        "«начни задание {}».".format(m["id"], len(m["steps"]), m["id"]))
            if not confirm("Задание «{}» из {} шагов: {}. Начинать?".format(m["title"], len(m["steps"]), ms.plan_text(m))):
                return ("План записан (задание №{}), но не начинаю. Можно поправить план словами — я составлю новый, "
                        "или скажите «начни задание {}».".format(m["id"], m["id"]))
            ms.missions.approve(m["id"])
            return ("Начинаю задание №{}: шаги пойдут по одному, между ними со мной можно говорить. Скажи пользователю коротко, "
                    "что начинаешь; шаги делать сейчас НЕ надо — я дам их по очереди.".format(m["id"]))
        if action == "report":
            m = ms.missions.report(int(a.get("id") or 0), a.get("outcome"), a.get("result") or "", a.get("question") or "")
            if m["status"] == "waiting":
                return "Записала: задание ждёт ответа. Спроси пользователя: " + (m["question"] or "")
            if m["status"] == "blocked":
                return ("Записала: шаг не вышел, задание остановлено. Скажи пользователю, что мешает, и предложи: повторить "
                        "(«продолжи задание»), пропустить шаг или отменить.")
            if m["status"] == "done":
                return "Записала: это был последний шаг — задание готово. Подведи итог в двух-трёх фразах."
            return ("Записала шаг. Следующий шаг начнётся сам, без разрешения пользователя: скажи итог этого шага одной-двумя "
                    "фразами и не спрашивай, переходить ли дальше.")
        if action in ("list", "status"):
            items = ms.missions.all(include_closed=bool(a.get("all")))
            if not items:
                return "Незаконченных заданий нет."
            return "\n".join(ms.describe(m) for m in items)
        if action == "show":
            m = ms.missions.get(int(a["id"])) if str(a.get("id") or "").isdigit() else _pick(a)
            return ms.describe(m, full=True) if m else "Нет такого задания."
        m = _pick(a)
        if action in ("resume", "start"):
            if m["status"] == "planned":
                if not confirm("Начать задание «{}»: {}?".format(m["title"], ms.plan_text(m))):
                    return "Не начинаю."
                ms.missions.approve(m["id"])
            else:
                ms.missions.resume(m["id"], a.get("answer") or "")
            return "Продолжаю задание №{}: следующий шаг дам сама, когда закончишь говорить.".format(m["id"])
        if action == "skip":
            ms.missions.skip(m["id"])
            return "Пропустила шаг, задание №{} идёт дальше.".format(m["id"])
        if action == "cancel":
            if not confirm("Отменить задание «{}»? Сделано {} из {} шагов.".format(m["title"], m["done_n"], len(m["steps"]))):
                return "Не отменяю."
            ms.missions.cancel(m["id"])
            return "Задание №{} отменено.".format(m["id"])
    except ms.MissionError as e:
        return "Не могу: {}.".format(e)
    return "Неизвестное действие: " + action
