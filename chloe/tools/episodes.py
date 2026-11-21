"""Идеи серий для канала — список в окне «Студия». «Запиши идею серии: …», «придумай три идеи серий»."""
from .. import studio_board as SB


def tool_episodes(a):
    action = a.get("action", "list")
    if action == "add_idea":
        texts = a.get("ideas") or ([a["text"]] if a.get("text") else [])
        if not texts:
            return "Нужна идея (text) или несколько (ideas)."
        before = len(SB.ideas())
        for t in texts[:10]:
            SB.add_idea(t, "Chloe", a.get("why", ""))
        new = len(SB.ideas()) - before
        return "Записала в «Студию» новых идей: {}{}. Владелец увидит их в окне «Студия» и запустит любую одной кнопкой.".format(
            new, " (остальные там уже были)" if new < len(texts[:10]) else "")
    if action == "remove_idea":
        return "Убрала." if SB.remove_idea(int(a.get("id") or 0)) else "Нет такой идеи."
    if action == "board":
        eps = SB.episodes(15)
        if not eps:
            return "Серий пока нет."
        return "\n".join("«{}» — {}{}".format(e["title"], e["stage_ru"], ", " + e["job"]["step"] if e.get("job") else "") for e in eps)
    items = SB.ideas()
    return "Идеи серий:\n" + "\n".join("#{} {}{}".format(i["id"], i["text"], " — " + i["why"] if i.get("why") else "") for i in items) \
        if items else "Идей серий пока нет."
