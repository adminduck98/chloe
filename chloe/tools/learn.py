"""Инструменты обучения: свой навык или сценарий, урок, забыть урок, что выучено."""
from .. import learning, skillbook


def tool_save_skill(a):
    triggers = a.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [triggers]
    path = learning.save_skill(a["name"], a["when"], a["steps"], triggers, a.get("from_last_task", True))
    s = skillbook.get(learning.slug(a["name"]))
    what = "Сценарий" if triggers else "Навык"
    said = " Запускается словами: {}.".format(", ".join("«{}»".format(t) for t in triggers)) if triggers else ""
    return "{} «{}» сохранён ({}).{}".format(what, s["name"] if s else a["name"], path, said)


def tool_learn_lesson(a):
    n = learning.learn_lesson(a["text"])
    return "Урок записан (всего правил: {}). Теперь он в каждой подсказке.".format(n)


def tool_forget_lesson(a):
    gone = learning.forget_lesson(a["number"])
    return "Забыла правило: {}".format(gone) if gone else "Не найдено правило с номером {}.".format(a["number"])


def tool_learned_list(_):
    learned = [s for s in skillbook.all_skills() if "Выучено со слов пользователя" in s["body"]]
    parts = []
    if learned:
        parts.append("Выученные навыки и сценарии:\n" + "\n".join(
            "- {}{}: {}".format(s["name"], " (слова: {})".format(", ".join(learning.triggers_of(s))) if learning.triggers_of(s) else "",
                                s["description"][:120]) for s in learned))
    if learning.lessons():
        parts.append(learning.lessons_prompt())
    return "\n".join(parts) or "Пока ничему не научена."
