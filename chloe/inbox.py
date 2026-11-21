"""Входящие от Chloe: всё, что ждёт решения владельца или готово к просмотру, — одним списком для значка в шапке.

Ничего не хранит само: собирает из Action Center (вопрос «да/нет», улучшения лаборатории, цели, посты),
фоновых работ (готовые картинки, ролики, озвучка) и подсказок. У каждой записи — устойчивый key
(окно помнит, что уже видено) и действия: answer — ответить «да/нет», say — передать Chloe просьбу,
open — открыть файл, dismiss — убрать подсказку.
"""
import time

READY_HOURS = 24          # готовые работы показываем сутки


def _waiting():
    out = []
    try:
        from .actions import waiting
    except Exception:
        return out
    for w in waiting():
        kind = w.get("kind")
        item = {"key": "{}:{}".format(kind, w.get("id") or w.get("what", "")[:60]), "kind": kind, "title": w.get("what", ""),
                "ts": w.get("since"), "actions": []}
        if kind == "question":
            item.update(group="Ждёт ответа", urgent=True,
                        actions=[{"label": "да, делай", "do": "answer", "arg": True}, {"label": "нет", "do": "answer", "arg": False}])
        elif kind == "lab":
            item.update(group="Ждёт решения",
                        actions=[{"label": "показать", "do": "say", "arg": "покажи улучшение номер {}".format(w["id"])},
                                 {"label": "внедрить", "do": "say", "arg": "внедри улучшение номер {}".format(w["id"])}])
        elif kind == "goal":
            item.update(group="Цели", actions=[{"label": "что дальше?", "do": "say", "arg": "что дальше по цели {}".format(w["id"])}])
        elif kind == "post":
            item.update(group="Ждёт решения", actions=[{"label": "показать пост", "do": "say", "arg": "покажи пост номер {}".format(w["id"])}])
        else:
            item["group"] = "Ждёт решения"
        out.append(item)
    return out


def _ready(now):
    out = []
    try:
        from .tools.media import NAMES, jobs
    except Exception:
        return out
    for jid, j in sorted(jobs.items()):
        if j["state"] == "работаю" or now - j["started"] > READY_HOURS * 3600:
            continue
        name = NAMES.get(j["kind"], ("Работа",))[0]
        if j["state"] == "готово":
            files = j.get("result") or []
            out.append({"key": "media:{}".format(jid), "kind": "ready", "group": "Готово", "ts": j["started"],
                        "title": "{} «{}» готово".format(name, j["prompt"][:60]), "sub": ", ".join(files)[:160],
                        "actions": ([{"label": "открыть", "do": "open", "arg": files[0]}] if files else []) +
                                   ([{"label": "в Файлах", "do": "reveal", "arg": files[0]}] if files else [])})
        else:
            out.append({"key": "media:{}".format(jid), "kind": "failed", "group": "Не получилось", "ts": j["started"],
                        "title": "{} «{}» — ошибка".format(name, j["prompt"][:60]), "sub": str(j.get("result") or "")[:160],
                        "actions": [{"label": "попробовать снова", "do": "say", "arg": "попробуй ещё раз: {}".format(j["prompt"][:200])}]})
    return out


def _tips():
    try:
        from . import proactive

        tips = proactive.collect()[:6]
    except Exception:
        return []
    out = []
    for t in tips:
        acts = [{"label": "да, сделай", "do": "say", "arg": t["say"]}] if t.get("say") else []
        acts.append({"label": "не надо", "do": "dismiss", "arg": t["key"]})
        out.append({"key": "tip:" + t["key"], "kind": "tip", "group": "Подсказки", "title": t["text"], "sub": t.get("why", ""),
                    "ts": None, "urgent": t.get("priority") == 1, "actions": acts})
    return out


def collect(now=None):
    now = now or time.time()
    items = _waiting() + _ready(now) + _tips()
    order = {"Ждёт ответа": 0, "Готово": 1, "Ждёт решения": 2, "Не получилось": 3, "Цели": 4, "Подсказки": 5}
    items.sort(key=lambda i: (order.get(i.get("group"), 9), -(i.get("ts") or 0)))
    return items
