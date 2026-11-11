"""Proactive Intelligence — Chloe сама замечает, что стоит сделать, и предлагает. Насколько активно — решает пользователь.

Режимы:
- «Тихо» (silent) — ничего не предлагает сама; работают только то, что пользователь завёл (напоминания, автоматизации);
- «Подсказки» (suggest, по умолчанию) — подсказки видны в «Действиях», вслух не звучат;
- «Сама предлагает» (proactive) — ещё и говорит вслух: не чаще раза в 2 часа, с 9 до 22, когда Chloe свободна,
  одну, самую важную, и каждую — не чаще раза в день.
У каждой подсказки — что предлагается, ПОЧЕМУ (с цифрами) и откуда это видно. «Не надо» — подсказка молчит неделю.
Подсказки только предлагают: сделать что-то — по слову пользователя, обычным путём со всеми проверками.
"""
import time

from .settings import settings

MODES = {"silent": "Тихо", "suggest": "Подсказки", "proactive": "Сама предлагает"}
SNOOZE_DAYS = 7
SAY_GAP = 2 * 3600
SAY_HOURS = (9, 22)
STALE_PROJECT_DAYS = 14


def mode():
    m = settings.get("proactive_mode") or "suggest"
    return m if m in MODES else "suggest"


def set_mode(m):
    if m not in MODES:
        raise ValueError("режим: silent, suggest или proactive")
    settings.set("proactive_mode", m)
    return m


def tip(key, text, why, source, priority=2, say=None):
    """priority: 1 — важно, 2 — полезно, 3 — мелочь. say — фраза, которой согласиться («да, разбери»)."""
    return {"key": key, "text": text, "why": why, "source": source, "priority": priority, "say": say}


# --- источники подсказок ---
def from_projects(now):
    out = []
    from .project_memory import project_memory as pm

    for name in pm.projects():
        tasks = pm.tasks(name)
        open_ = [t for t in tasks if t["status"] != "done"]
        if not open_:
            continue
        last = max([t["updated"] or t["created"] or 0 for t in tasks] + [n["ts"] or 0 for n in pm.notes(name, 1)] or [0])
        days = int((now - last) // 86400)
        if days >= STALE_PROJECT_DAYS:
            out.append(tip("project-stale:" + name, "Вернуться к проекту «{}»?".format(name),
                           "не обновлялся {} дней, открыто задач: {}".format(days, len(open_)), "проекты", 2, "что по проекту " + name))
        doing = [t for t in tasks if t["status"] == "doing"]
        if doing:
            t = max(doing, key=lambda t: t["updated"] or 0)
            hours = int((now - (t["updated"] or now)) // 3600)
            if hours >= 12:
                out.append(tip("resume:{}".format(t["id"]), "Продолжим с последнего шага: «{}»?".format(t["title"][:80]),
                               "задача в работе с {} ч назад, проект «{}»".format(hours, name), "проекты", 2, "продолжим проект " + name))
    return out


def from_goals(now):
    from .goals import goals

    return [tip("goal:{}:{}".format(x["goal"]["id"], x["why"].split(" ")[0]), "Цель «{}»".format(x["goal"]["title"][:60]),
                x["why"], "цели", 1 if "прошёл" in x["why"] or "до срока" in x["why"] else 2, "что дальше по цели {}".format(x["goal"]["id"]))
            for x in goals.attention(now)]


def from_lab(now):
    out = []
    from . import lab as L

    proposed = {r["title"] for r in L.lab.items(50)}
    for p in L.problems(7, now):
        if p["count"] >= 3 and p["kind"] != "correction" and p["title"] not in proposed:
            out.append(tip("lab:" + p["key"], "Разобрать повторяющуюся ошибку?", "«{}» — {} раз за неделю".format(p["title"][:70], p["count"]),
                           "журнал → лаборатория", 2, "разбери свои ошибки"))
            break                                            # одной хватит: остальные — в «разбери свои ошибки»
    for r in L.lab.items(20):
        if r["status"] == "ready":
            out.append(tip("lab-ready:{}".format(r["id"]), "Улучшение №{} ждёт решения".format(r["id"]), r["title"][:80],
                           "лаборатория", 2, "покажи улучшение {}".format(r["id"])))
    return out


def from_health(now):
    out = []
    from . import system_state as ss

    for x in ss.quick():
        if x["level"] == "fail":
            what = "{} {}".format(x["area"], x["name"].lower()) if x["area"] == "Ошибки" else x["name"]
            out.append(tip("health:" + x["name"], "Разобраться: {}".format(what), x["detail"], "самопроверка", 1, "проверь себя"))
    from .security import security

    n = len(security.events(7, "injection"))
    if n:
        out.append(tip("security:injection", "Посмотреть попытки командовать мной?", "за неделю {} шт., ничего не выполнено".format(n),
                       "журнал безопасности", 2, "были попытки?"))
    return out


def from_money(now):
    out = []
    from .finance import finance

    for r in finance.due(1):
        out.append(tip("pay:{}:{}".format(r["id"], r["next_date"]), "Скоро списание: {}".format(r["name"]),
                       "{} {}, дата {}".format(r["amount"], r["currency"], r["next_date"]), "подписки", 2))
    from . import qwen_plan

    st = qwen_plan.state()
    if st.get("warned_level", 0) >= 0.8:
        out.append(tip("qwen:{}".format(st.get("warned_period")), "Кредиты Qwen подходят к концу",
                       "потрачено больше {:.0f}%".format(st["warned_level"] * 100), "Bailian CLI", 1, "сколько осталось кредитов qwen"))
    return out


def from_waiting(now):
    out = []
    from .missions import missions

    for m in missions.all():
        if m["status"] in ("waiting", "blocked", "paused"):
            why = {"waiting": "ждёт ответа: " + (m["question"] or "")[:80], "blocked": "шаг не вышел",
                   "paused": "прервано перезапуском"}[m["status"]]
            out.append(tip("mission:{}:{}".format(m["id"], m["status"]), "Задание «{}» стоит".format(m["title"][:60]),
                           "{}, сделано {} из {}".format(why, m["done_n"], len(m["steps"])), "задания", 1, "продолжи задание " + str(m["id"])))
    from .social import social

    for p in social.posts():
        if p["due"] and p["status"] == "draft" and p["due"] - now < 86400:
            out.append(tip("post:{}".format(p["id"]), "Пост №{} не одобрен".format(p["id"]), "выйти должен {}".format(
                time.strftime("%d.%m %H:%M", time.localtime(p["due"]))), "соцсети", 1, "покажи пост {}".format(p["id"])))
    return out


SOURCES = (from_health, from_goals, from_waiting, from_money, from_projects, from_lab)


def snoozed(now=None):
    now = now or time.time()
    return {k: until for k, until in (settings.get("proactive_snooze") or {}).items() if until > now}


def collect(now=None):
    """Все подсказки, кроме отложенных, — важные первыми. Сломанный источник не мешает остальным."""
    now = now or time.time()
    out = []
    for src in SOURCES:
        try:
            out += src(now)
        except Exception as e:
            print("[подсказки: {} — {}]".format(src.__name__, type(e).__name__))
    skip = snoozed(now)
    seen, unique = set(), []
    for t in sorted(out, key=lambda t: t["priority"]):
        if t["key"] not in skip and t["key"] not in seen:
            seen.add(t["key"])
            unique.append(t)
    return unique


def snooze(key, days=SNOOZE_DAYS, now=None):
    now = now or time.time()
    s = snoozed(now)
    s[key] = now + days * 86400
    settings.set("proactive_snooze", s)


def pick_to_say(tips, now=None):
    """Что сказать вслух сейчас (режим «Сама предлагает»), или None."""
    now = now or time.time()
    if mode() != "proactive" or not tips:
        return None
    hour = time.localtime(now).tm_hour
    if not SAY_HOURS[0] <= hour < SAY_HOURS[1]:
        return None
    said = settings.get("proactive_said") or {}
    if now - max(said.values() or [0]) < SAY_GAP:
        return None
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    for t in tips:
        last = said.get(t["key"])
        if not last or time.strftime("%Y-%m-%d", time.localtime(last)) != today:
            return t
    return None


def mark_said(key, now=None):
    said = {k: v for k, v in (settings.get("proactive_said") or {}).items() if (now or time.time()) - v < 7 * 86400}
    said[key] = now or time.time()
    settings.set("proactive_said", said)


def phrase(t):
    return "{} {}.{}".format(t["text"], t["why"][0].upper() + t["why"][1:], " Скажите «{}», если да.".format(t["say"]) if t["say"] else "")


def watcher(say, every=300, stop=None):
    """Раз в 5 минут: в режиме «Сама предлагает» — одна подсказка вслух, когда можно."""
    from .signals import busy, state

    while not (stop and stop.is_set()):
        try:
            if mode() == "proactive" and not settings.get("safe_mode"):
                from .voice import voice

                idle = not (busy.is_set() or voice.saying or voice.awaiting) and time.time() > state.get("listen_until", 0) + 60
                if idle:
                    t = pick_to_say(collect())
                    if t:
                        mark_said(t["key"])
                        say(phrase(t))
                        state["listen_until"] = time.time() + 30          # можно ответить без «Хлоя»
        except Exception as e:
            print("[подсказки: {}]".format(str(e)[:80]))
        (stop.wait(every) if stop else time.sleep(every))


def start(say):
    import threading

    threading.Thread(target=watcher, args=(say,), daemon=True, name="proactive").start()
