"""Инструмент proactive — подсказки Chloe и насколько активно она их предлагает."""
from .. import proactive as pr


def tool_proactive(a):
    action = a.get("action", "list")
    if action == "mode":
        m = (a.get("mode") or "").strip()
        alias = {"тихо": "silent", "молча": "silent", "подсказки": "suggest", "сама": "proactive", "активно": "proactive"}
        m = alias.get(m.lower(), m)
        if not m:
            return "Сейчас: «{}». Режимы: Тихо (silent), Подсказки (suggest), Сама предлагает (proactive).".format(pr.MODES[pr.mode()])
        try:
            pr.set_mode(m)
        except ValueError as e:
            return str(e)
        return {"silent": "Хорошо: сама ничего не предлагаю — только то, что ты завёл (напоминания, автоматизации).",
                "suggest": "Хорошо: подсказки — в «Действиях», вслух не говорю.",
                "proactive": "Хорошо: буду иногда предлагать сама — не чаще раза в 2 часа, с 9 до 22 и когда ты не занят."}[m]
    tips = pr.collect()
    if action == "dismiss":
        n = a.get("number")
        key = a.get("key")
        if n and 1 <= int(n) <= len(tips):
            key = tips[int(n) - 1]["key"]
        if not key:
            return "Какую подсказку отложить? Номер — из списка."
        pr.snooze(key)
        return "Хорошо, об этом неделю молчу."
    if not tips:
        return "Сейчас мне нечего предложить — всё в порядке. Режим: «{}».".format(pr.MODES[pr.mode()])
    lines = ["Режим: «{}». Что я заметила:".format(pr.MODES[pr.mode()])]
    for i, t in enumerate(tips[:10], 1):
        lines.append("{}. {} — {} (откуда: {}){}".format(i, t["text"], t["why"], t["source"], "; скажи «{}»".format(t["say"]) if t["say"] else ""))
    return "\n".join(lines) + "\nПредлагай, а не делай: действовать — только после слова пользователя."
