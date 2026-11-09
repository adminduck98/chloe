"""«Хлоя, покажи, как ты это сделала»: мозг проигрывает путь прошлой задачи шаг за шагом — по журналу, как было на самом деле."""
import json

from ..brain import brain
from ..experience import things_of
from ..journal import journal


def past_task(back=1):
    """(просьба, шаги) задачи, которая была back-й по счёту до текущей; шаги — только реальные вызовы инструментов."""
    with journal.lock:
        asks = journal.db.execute(
            "SELECT id, title FROM events WHERE kind = 'heard' AND id != ? AND EXISTS "
            "(SELECT 1 FROM events t WHERE t.task = events.id AND t.kind = 'tool') ORDER BY id DESC LIMIT 1 OFFSET ?",
            (journal.task or -1, max(0, int(back) - 1))).fetchone()
        if asks is None:
            return None, []
    return asks["title"], steps_of(asks["id"])


def steps_of(task_id):
    """Шаги задачи из журнала: навык, сколько секунд, получилось ли, какие предметы трогала."""
    with journal.lock:
        rows = journal.db.execute("SELECT skill, detail, ok FROM events WHERE task = ? AND kind = 'tool' ORDER BY id",
                                  (task_id,)).fetchall()
    steps = []
    for r in rows:
        d = json.loads(r["detail"] or "{}")
        steps.append({"skill": r["skill"], "seconds": d.get("seconds", 0.5), "ok": bool(r["ok"]), "tool": d.get("tool", ""),
                      "things": things_of(d.get("tool", ""), d.get("args") or {}, bool(r["ok"]))})
    return steps


def tool_replay_task(a):
    title, steps = past_task(a.get("back") or 1)
    if title is None:
        return "Не найдено прошлых задач с действиями — пока нечего показать."
    brain.replay(title, steps)
    total = sum(s["seconds"] for s in steps)
    path = " → ".join(s["skill"] + ("" if s["ok"] else " (ошибка)") for s in steps)
    return "Показываю в мозге задачу «{}»: {} шагов, {:.0f} с. Путь: {}.".format(title, len(steps), total, path)
