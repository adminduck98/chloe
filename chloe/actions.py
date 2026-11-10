"""Action Center — всё, что Chloe делает, в одном месте: сейчас, ждёт решения, сделано сегодня, ошибки, отмена.

Ничего не хранит само: собирает из журнала (шаги и подтверждения), истории изменений файлов (отмена), фоновых работ
(картинки, ролики, озвучка, лаборатория), запланированных постов и напоминаний, предложений лаборатории.
"""
import json
import re
import time

REFUSAL = ("Пользователь", "Отказано", "Не публикую", "Не озвучиваю", "Не делаю", "Не добавила", "Не удаляю", "Оставила")


def _day_start(now=None):
    t = time.localtime(now or time.time())
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def now_doing():
    out = []
    try:
        from .signals import busy

        if busy.is_set():
            out.append({"what": "думаю или выполняю просьбу", "since": None})
    except Exception:
        pass
    try:
        from .tools.media import NAMES, jobs

        for i, j in sorted(jobs.items()):
            if j["state"] == "работаю":
                out.append({"what": "{} «{}»{}".format(NAMES[j["kind"]][0], j["prompt"][:60], ", " + j["step"] if j.get("step") else ""),
                            "since": j["started"]})
    except Exception:
        pass
    try:
        from .agents import AGENTS, runs

        for r in runs.running():
            out.append({"what": "{} (агент №{}): {}".format(AGENTS.get(r["agent"], {}).get("name", r["agent"]), r["id"], r["task"][:70]),
                        "since": r["started"]})
    except Exception:
        pass
    try:
        from .tools.improve import _running

        if _running.is_set():
            out.append({"what": "лаборатория разбирает ошибку", "since": None})
    except Exception:
        pass
    return out


def waiting():
    """Что ждёт решения пользователя."""
    out = []
    try:
        from .voice import voice

        if getattr(voice, "pending", None):
            out.append({"kind": "question", "what": voice.pending["question"], "since": voice.pending["since"]})
    except Exception:
        pass
    try:
        from .lab import lab

        for r in lab.items(50):
            if r["status"] == "ready":
                out.append({"kind": "lab", "id": r["id"], "what": "улучшение №{}: {}".format(r["id"], r["title"][:80]), "since": r["ts"]})
    except Exception:
        pass
    try:
        from .goals import goals

        for x in goals.attention():
            out.append({"kind": "goal", "id": x["goal"]["id"], "what": "цель «{}»: {}".format(x["goal"]["title"][:60], x["why"]),
                        "since": x["goal"]["updated"]})
    except Exception:
        pass
    try:
        from .social import NETWORKS, social

        for p in social.posts():
            if p["due"] and p["status"] in ("draft", "approved"):
                out.append({"kind": "post", "id": p["id"], "since": p["due"],
                            "what": "пост №{} в {} — {}".format(p["id"], NETWORKS[p["network"]],
                                                               "уйдёт сам" if p["status"] == "approved" else "не одобрен")})
    except Exception:
        pass
    return out


def upcoming(hours=24, now=None):
    now = now or time.time()
    out = []
    try:
        from .reminders import reminders

        for r in reminders.pending():
            if r["due"] - now <= hours * 3600:
                out.append({"what": "напоминание: " + r["text"][:80], "at": r["due"]})
    except Exception:
        pass
    try:
        from .workflows import workflows

        for w in workflows.upcoming(hours, now):
            out.append({"what": "автоматизация «{}»".format(w["name"]), "at": w["next_run"]})
    except Exception:
        pass
    try:
        from .finance import finance

        for r in finance.due(1):
            out.append({"what": "списание: {} {}".format(r["name"], r["amount"]), "at": None})
    except Exception:
        pass
    return out


def today(now=None, limit=200):
    """Шаги и подтверждения за сегодня: [{id, ts, kind, skill, title, ok, error}] — новые сверху."""
    from .journal import journal

    start = _day_start(now)
    rows = []
    with journal.lock:
        cur = journal.db.execute("SELECT id, ts, kind, skill, title, ok, detail FROM events WHERE ts >= ? AND kind IN ('tool', 'confirm') "
                                 "ORDER BY id DESC LIMIT ?", (start, limit))
        for r in cur:
            result = ""
            if r[2] == "tool" and not r[5]:
                try:
                    d = json.loads(r[6] or "{}")
                    d = json.loads(d) if isinstance(d, str) else d
                    result = str(d.get("result", ""))
                except ValueError:
                    pass
            refused = result.startswith(REFUSAL) or (r[2] == "confirm")
            rows.append({"id": r[0], "ts": r[1], "kind": r[2], "skill": r[3], "title": r[4], "ok": bool(r[5]),
                         "error": (not r[5]) and not refused, "result": re.sub(r"https?://([^/\s)]+)\S*", r"\1", result)[:200]})
    return rows


def undoable(limit=20):
    """Последние изменения файлов, которые можно отменить."""
    try:
        from .changes import changes

        return [c for c in changes.list(limit) if not c.get("undone")][:limit]
    except Exception:
        return []


def overview(now=None):
    from . import safemode

    steps = today(now)
    tools = [s for s in steps if s["kind"] == "tool"]
    return {"safe_mode": safemode.on(), "safe_since": safemode.since(), "now": now_doing(), "waiting": waiting(),
            "upcoming": upcoming(now=now), "today": steps,
            "counts": {"steps": len(tools), "ok": sum(1 for s in tools if s["ok"]), "errors": sum(1 for s in steps if s["error"]),
                       "asked": sum(1 for s in steps if s["kind"] == "confirm")},
            "undo": undoable(), "workflows": flows()}


def flows():
    try:
        from .workflows import workflows

        return [{"id": w["id"], "name": w["name"], "when": w["when"], "enabled": bool(w["enabled"]), "next": w["next_run"],
                 "last": w["last_run"], "runs": w["runs"], "instruction": w["instruction"][:200]} for w in workflows.all()]
    except Exception:
        return []
