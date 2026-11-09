"""Память голосом: «запомни…», «забудь…»."""
from ..brain import brain
from ..memory import forget_memory, memory
from ..voice import confirm
from ..secret import has_secret


def tool_remember(a):
    if has_secret(a["text"]):
        return ("Отказано: ключи, токены и пароли я не запоминаю — память уходит модели с каждой просьбой "
                "и видна в окне и на телефоне. Ключ уже хранится там, где его взяли (например, в ~/.config/chloe/keys.env).")
    zone = a.get("zone") or "Память"
    item, what, before = memory.remember(a["text"], zone)
    if what == "same":
        return "Это я уже помню (запись [{}]).".format(item["id"])
    if what == "updated":
        brain.js("chloeRewrite", before, item["text"])
        return "Обновила запись [{}]: было «{}», теперь «{}».".format(item["id"], before, item["text"])
    brain.remember(a["text"], zone)
    return "Запомнила."


def tool_forget(a):
    m = memory.get(int(a["id"]))
    if m is None:
        return "Не найдено воспоминание с номером {}.".format(a["id"])
    if not confirm("Забыть: «" + m["text"] + "»?"):
        return "Пользователь не разрешил забыть."
    forget_memory(m["id"])
    return "Забыла: " + m["text"]


def tool_sleep_now(a):
    from ..sleep import go_to_sleep

    r = go_to_sleep()
    return ("Сплю. Объединила повторяющихся воспоминаний: {}, укрепила важных: {}, переиграла задач дня: {}, "
            "темы в мозге: {}. Скажите «Хлоя», чтобы разбудить.").format(
        len(r["merged"]), len(r["strong"]), len(r["tasks"]), ", ".join(r["zones"]) or "пока нет")
