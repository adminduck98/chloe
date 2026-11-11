"""Главный цикл и окно: слушать → дослушать → подумать → ответить; страница мозга и её API."""
import argparse
import http.server
import json
import os
import queue
import re
import socketserver
import threading
import time

from . import config
from .brain import brain
from . import remote, skillbook, snapshots
from .changes import changes
from .ears import ears, has_wake, is_wake_word
from .ears import install as ears_install
from .config import ACTIVE_WINDOW, BRAIN_FILE, DATA, EXIT_WORDS, STOP_WORDS, UI_DIR, WAKE_WORDS
from .journal import journal
from .learning import match_trigger
from .reminders import watcher as reminder_watcher
from . import sleep
from .sleep import start as sleep_watcher
from .memory import forget_memory, memory, rewrite_memory
from .settings import settings
from .signals import Typed, busy, commands, heard_q, interrupt, is_stop, seen_text, state
from .thinking import ask_short, forget_old, make_client, think
from .tools import SKILLS
from .tools.system import tool_open_path
from .tools.weather import find_city, place_text
from .vision import vision
from .voice import finish_speech, listener, recorder, voice


WAKE_RE = re.compile(r"^\W*(?:{})\b[\s,.!:-]*".format("|".join(WAKE_WORDS)), re.IGNORECASE)


def strip_wake(text):
    m = WAKE_RE.match(text)
    if m:
        return text[m.end():], True
    m = re.match(r"^\W*(\w+)\b[\s,.!:-]*", text)
    if m and is_wake_word(m.group(1)):   # «Хлоа, …», «Клое, …» — распознавание исказило имя
        return text[m.end():], True
    return text, has_wake(text)


WORK_ON = ("приступаем к работе", "приступим к работе", "приступаем к проекту", "начинаем работать")
WORK_OFF = ("не напоминай о задачах", "не напоминай о проектах", "заканчиваем работу", "закончили работу")


def work_mode_phrase(low):
    """«Приступаем к работе» — включить напоминание о задачах при старте; «заканчиваем работу» — выключить.
    Возвращает True/False, если фраза есть, иначе None. Команда всё равно идёт в мозг — он и начинает работу."""
    low = " ".join(low.replace("ё", "е").split())
    if any(w in low for w in WORK_OFF):
        return False
    if any(w in low for w in WORK_ON):
        return True
    return None


def startup_notices():
    """При включении — о пакете Qwen: исчерпан или подходит к концу (это не задачи, поэтому всегда)."""
    try:
        from . import config, qwen_plan

        if not config.QWEN_KEY:
            return ""
        if qwen_plan.exhausted():
            return " Кредиты Qwen закончились — пока отвечаю через запасную модель."
        w = qwen_plan.warning(qwen_plan.from_cli(timeout=8))
        return " " + w if w else ""
    except Exception:
        return ""


def payment_notice(today=None):
    """При включении, раз в день — что спишется сегодня или завтра (утренняя сводка говорит об этом сама)."""
    try:
        import datetime

        from .finance import finance, upcoming_text

        today = today or datetime.date.today()
        if settings.get("pay_notice_day") == today.isoformat():
            return ""
        text = upcoming_text(finance.due(1, today), today)
        if text:
            settings.set("pay_notice_day", today.isoformat())
        return " " + text if text else ""
    except Exception:
        return ""


def startup_reminder():
    """При включении — важные задачи проектов (приоритет «важно», не сделаны).
    Только после «приступаем к работе»: пока пользователь этого не сказал, Хлоя о задачах молчит."""
    try:
        from .permissions import permissions
        from .project_memory import project_memory
        from .settings import settings

        if not settings.get("work_mode", False):
            return ""
        if permissions.level("projects") == "block":
            return ""
        tasks = project_memory.important_open(3)
    except Exception:
        return ""
    if not tasks:
        return ""
    return " Напоминаю важное: " + "; ".join(
        ("{} (проект {})".format(t["title"], t["project"]) if len({x["project"] for x in tasks}) > 1 else t["title"]) for t in tasks) + "."


def assistant(args):
    if not config.has_key():
        voice.say("Не задан ключ: нужен DASHSCOPE_API_KEY (Qwen), DEEPSEEK_API_KEY, GEMINI_API_KEY или ANTHROPIC_API_KEY "
                  "в файле ~/.config/chloe/keys.env. Я не могу думать без него.")
        return
    print("[мозг: {} · быстрый {} · сильный {}]".format(config.PROVIDER, config.MODEL_FAST, config.MODEL_STRONG))
    client = make_client()
    messages = []
    from .greeting import greeting
    from .tools.news import morning_due

    if morning_due():   # первый запуск утром и сводка включена — сразу расскажет: погода, дела, новости
        voice.say(greeting(brief=True) + startup_notices())
        commands.put(Typed("Утренняя сводка", "local"))
    else:
        voice.say(greeting() + startup_notices() + payment_notice() + startup_reminder())
    state["listen_until"] = time.time() + ACTIVE_WINDOW
    if voice.enabled and not args.text:
        threading.Thread(target=recorder, daemon=True).start()
        threading.Thread(target=listener, daemon=True).start()
    threading.Thread(target=reminder_watcher, args=(voice.say,), daemon=True).start()
    from .tools import social as social_tool

    social_tool.start(voice.say)   # запланированные посты: одобренные — в канал, остальные — напоминание и пакет
    from . import workflows as wf

    wf.start()                     # автоматизации: по расписанию и по событиям — как обычные просьбы, со всеми проверками
    from . import missions, proactive

    proactive.start(voice.say)     # подсказки: в режиме «Сама предлагает» — иногда вслух, по правилам
    missions.start(voice.say)      # задания: шаги по одному, когда Chloe свободна; прерванные — по слову «продолжи задание»
    from . import visual as visual_mem

    visual_mem.start()             # визуальная память: новые скриншоты и картинки — описание и поиск
    vision.on_window = lambda title, private: brain.js("chloeSee", "" if private else title[:80], bool(private), vision.enabled)
    vision.start()   # постоянное зрение: глаза смотрят на экран в фоне
    sleep.namer = lambda prompt: ask_short(client, prompt)   # названия тем во сне
    sleep_watcher()   # ночью, в тишине — уборка памяти

    idle = {"sent": False}

    def go_idle():   # «спокойна» — в окно и на телефоны только при смене, а не каждую секунду
        if not idle["sent"]:
            brain.state("idle")
            idle["sent"] = True

    while True:
        mark = len(messages)   # при ошибке убираем только эту просьбу, а не весь разговор
        try:
            typed = None
            try:
                typed = commands.get_nowait()
            except queue.Empty:
                pass

            if typed:
                command = str(typed)
                state["where"] = getattr(typed, "where", "local")   # с телефона — ответ звучит на телефоне
            elif args.text:
                command = input("Вы: ").strip()
            else:
                try:
                    # 0,1 с, а не секунда: команда, набранная в окне или на телефоне, начинается сразу
                    heard = heard_q.get(timeout=0.1)
                except queue.Empty:
                    heard = ""
                if not heard:
                    if time.time() > state["listen_until"]:
                        go_idle()
                    continue
                state["where"] = "local"        # сказано в микрофон компьютера — компьютер и отвечает
                began = time.time()             # окно «без Хлоя» проверяем по началу фразы, а не по концу:
                heard = finish_speech(heard)    # пока она дослушивала (музыка, длинная речь), окно могло закрыться
                print("Вы:", heard)
                command, woke = strip_wake(heard)
                if not woke and began > state["listen_until"]:
                    go_idle()
                    continue   # не обращались к Хлое
                brain.heard(heard)
                idle["sent"] = False
                if not command:
                    voice.say("Да?")
                    state["listen_until"] = time.time() + ACTIVE_WINDOW
                    continue

            low = command.lower().strip(" .!?")
            if not low:
                continue
            idle["sent"] = False   # дальше — думает и говорит; потом снова «спокойна»
            journal.add("heard", "Голос", command, {"typed": bool(typed or args.text)})
            seen_text.append(command)   # адрес, названный пользователем, можно открыть
            mode = work_mode_phrase(low)
            if mode is not None:
                from .settings import settings
                settings.set("work_mode", mode)
                print("[работа: напоминание о задачах при включении {}]".format("включено" if mode else "выключено"))
            if low in EXIT_WORDS:
                voice.say("До встречи!")
                os._exit(0)
            if low in STOP_WORDS:
                voice.say("Хорошо.")
                continue
            scenario = match_trigger(command)
            if scenario:   # слово сценария: «работаем» — выполнить свой навык
                print("[сценарий: {}]".format(scenario["name"]))
                command = "Сценарий «{}»: выполни свой навык «{}» — сначала прочитай его (use_skill).".format(
                    command.strip(" .!?"), scenario["name"])

            interrupt.clear()
            busy.set()   # пока она думает и отвечает, слух ловит только «стоп»
            mark = len(messages)
            try:
                started = time.time()
                answer = think(client, messages, command)
                print("[думала {:.1f} с]".format(time.time() - started))
                forget_old(messages)
                if answer and not interrupt.is_set():
                    voice.say(answer)
            finally:
                busy.clear()
            if interrupt.is_set():
                interrupt.clear()
                journal.add("stop", "Голос", "Вы сказали «стоп» — Chloe остановилась")
                voice.say("Остановилась.")
            brain.state("idle")
            state["listen_until"] = time.time() + ACTIVE_WINDOW
        except KeyboardInterrupt:
            os._exit(0)
        except Exception as e:
            print("[ошибка] " + str(e))
            # незаконченная просьба (вызов инструмента без ответа и т. п.) сломала бы следующие — убираем только её;
            # разговор до неё остаётся
            del messages[mark:]
            interrupt.clear()
            busy.clear()
            if "RESOURCE_EXHAUSTED" in str(e) or " 429" in str(e):
                voice.say("Бесплатный лимит Gemini пока закончился. Попробуйте позже.")
            elif any(w in str(e).lower() for w in ("timed out", "timeout", "deadline")):
                voice.say("Модель слишком долго не отвечает. Попробуйте ещё раз.")
            else:
                voice.say("Что-то пошло не так. Попробуйте ещё раз.")



class Api:
    """Вызывается из окна (JavaScript)."""

    def command(self, text, where="local"):
        if busy.is_set() and is_stop(str(text)):   # «стоп» из строки ввода тоже перебивает
            interrupt.set()
            voice.stop_audio()
            return
        commands.put(Typed(str(text), "phone" if where == "phone" else "local"))

    def save_brain(self, raw):
        snapshots.daily()   # копия дня — до первого сохранения
        if not raw:   # «Сбросить мозг»: сначала копия
            snapshots.before("перед-сбросом")
            BRAIN_FILE.unlink(missing_ok=True)
            return True
        try:
            data = json.loads(raw)
        except ValueError:
            return False   # битый мозг не затирает хороший
        if not isinstance(data, dict) or not data.get("neurons"):
            return False   # пустой мозг вместо полного — тоже нет (стереть можно только сбросом)
        tmp = BRAIN_FILE.with_suffix(".tmp")
        tmp.write_text(raw, encoding="utf-8")
        tmp.replace(BRAIN_FILE)
        return True

    def load_brain(self):
        try:
            return BRAIN_FILE.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    # журнал: смотреть и удалять можно, изменять — нет
    def journal_list(self, query="", skill="", limit=100, before=0):
        return journal.list(str(query or ""), str(skill or ""), int(limit or 100), int(before or 0))

    def journal_get(self, eid):
        return journal.get(int(eid))

    def journal_delete(self, eid):
        return journal.delete(int(eid))

    def journal_clear(self):
        return journal.clear()

    # файлы: что Chloe меняла на диске — и отмена
    def changes_list(self, limit=100):
        return changes.list(int(limit or 100))

    def change_undo(self, cid):
        ok, message = changes.undo(int(cid), by="окно")
        return {"ok": ok, "message": message}

    def open_folder(self, path):
        """Показать папку в файловом менеджере — только если это папка с изменением из списка."""
        known = {c["folder"] for c in changes.list(500)}
        if str(path) not in known:
            return False
        tool_open_path({"path": str(path)})
        return True

    # память: что Chloe знает о вас — смотреть, добавлять, исправлять, удалять
    def memory_list(self):
        return list(reversed(memory.items))

    def memory_add(self, text, zone="Память"):
        text = str(text).strip()
        if not text:
            return None
        item = memory.add(text, str(zone or "Память"))
        brain.remember(text, item["zone"])
        journal.add("memory", "Память", "Вы добавили: " + text, {"id": item["id"], "text": text, "by": "окно"})
        return item

    def memory_edit(self, mid, text):
        text = str(text).strip()
        if not text:
            return False
        old = rewrite_memory(int(mid), text)
        if old is None:
            return False
        journal.add("memory", "Память", "Вы исправили: " + old + " → " + text, {"id": int(mid), "old": old, "new": text, "by": "окно"})
        return True

    # голос Светланы для телефона: телефон говорит тем же голосом, что и компьютер, а не своим
    def tts(self, text):
        import base64

        from .voice import voice_mp3

        data = voice_mp3(str(text)[:1200])
        if not data:
            return {"error": "Голос Светланы сейчас недоступен"}
        return {"audio": base64.b64encode(data).decode()}

    # проекты: задачи, решения, цели — панель «Проекты» в окне (на телефоне этих методов нет)
    def projects_list(self):
        from .project_memory import project_memory

        out = []
        for name in project_memory.projects():
            tasks = project_memory.tasks(name)
            out.append({"name": name, "todo": sum(t["status"] == "todo" for t in tasks),
                        "doing": sum(t["status"] == "doing" for t in tasks), "done": sum(t["status"] == "done" for t in tasks),
                        "updated": max([t["updated"] or 0 for t in tasks] + [n["ts"] or 0 for n in project_memory.notes(name, 1)] or [0])})
        return sorted(out, key=lambda p: -p["updated"])

    def project_get(self, name):
        from .project_memory import project_memory

        key = project_memory.resolve(name)
        return {"name": key, "tasks": project_memory.tasks(key), "notes": project_memory.notes(key, 50)}

    def project_task_add(self, name, title, priority=2):
        from .project_memory import project_memory

        if str(title).strip():
            first = project_memory.resolve(name) not in project_memory.projects()
            project_memory.add_task(name, str(title), int(priority or 2))
            if first:
                brain.remember(project_memory.resolve(name), "Проекты")
        return self.project_get(name)

    def project_task_status(self, tid, status):
        from .project_memory import project_memory

        t = project_memory.task(int(tid))
        if t:
            project_memory.set_status(t["id"], status)
            return self.project_get(t["project"])
        return {"error": "нет такой задачи"}

    def project_task_delete(self, tid):
        from .project_memory import project_memory

        t = project_memory.task(int(tid))
        if not t:
            return {"error": "нет такой задачи"}
        project_memory.delete_task(t["id"])   # кнопка в окне — уже согласие пользователя
        return self.project_get(t["project"])

    def project_note_add(self, name, kind, text):
        from .project_memory import project_memory

        if str(text).strip():
            first = project_memory.resolve(name) not in project_memory.projects()
            project_memory.add_note(name, kind, str(text))
            if first:
                brain.remember(project_memory.resolve(name), "Проекты")
        return self.project_get(name)

    # карта прав и Private Vault — только в окне на компьютере (телефону эти методы не доступны: менять права — за компьютером)
    def permissions_get(self):
        from .permissions import permissions, usage

        return permissions.map(usage(7))

    def permission_set(self, key, level):
        from .permissions import CATEGORIES, LEVEL_RU, permissions

        permissions.set_level(key, level)
        journal.add("brain", "Доступ", "Права: «{}» — {}".format(CATEGORIES[key][0], LEVEL_RU[level]), {"key": key, "level": level})
        return self.permissions_get()

    def vault_add(self, path):
        from .permissions import permissions
        from .tools.paths import P

        p = P(str(path).strip())
        if not str(path).strip() or not p.is_dir():
            return {"error": "Нет такой папки: " + str(path)}
        permissions.vault_add(p)
        journal.add("brain", "Доступ", "Private Vault: добавлена папка " + str(p), {"vault_add": str(p)})
        return self.permissions_get()

    def vault_remove(self, path):
        from .permissions import permissions

        permissions.vault_remove(path)
        journal.add("brain", "Доступ", "Private Vault: убрана папка " + str(path), {"vault_remove": str(path)})
        return self.permissions_get()

    # телефон-пульт: ссылка с кодом и QR-код (только в окне на компьютере, телефону этот метод не доступен)
    def phone_link(self):
        if not remote.ENABLED:
            return {"error": "Телефон выключен (CHLOE_PHONE=off)."}
        url = remote.link()
        return {"url": url, "svg": remote.qr_svg(url), "ip": remote.lan_ip(), "port": remote.PORT}

    # город пользователя: для погоды
    # ядро в окне: состояние всей системы одним запросом — модели, зрение, память, навыки, напоминания, расход
    def system_status(self):
        from . import usage as usage_mod
        from .reminders import reminders

        today = usage_mod.load().get(time.strftime("%Y-%m-%d"), {})
        models = [m for m in (config.MODEL_FAST, config.MODEL_STRONG, getattr(config, "MODEL_EYES", None)) if m]
        return {
            "provider": config.PROVIDER,
            "fast": config.MODEL_FAST, "strong": config.MODEL_STRONG, "eyes": getattr(config, "MODEL_EYES", None),
            "models": list(dict.fromkeys(models)),
            "vision": {"on": vision.enabled, "title": "" if vision.private else vision.title[:80], "private": vision.private},
            "memory": len(memory.items),
            "skills": len(skillbook.all_skills()),
            "reminders": len(reminders.pending()),
            "today": {"calls": sum(m.get("calls", 0) for m in today.values()),
                      "usd": round(sum(m.get("usd", 0.0) for m in today.values()), 4)},
            "busy": busy.is_set(),
        }

    # связи и история: граф знаний для панели «Связи»
    def graph_overview(self):
        from .graph import graph

        nodes, edges = graph.build()
        deg = {}
        for e in edges:
            if e["kind"] != "project":
                deg[e["a"]] = deg.get(e["a"], 0) + 1
                deg[e["b"]] = deg.get(e["b"], 0) + 1
        hubs = sorted((n for n in nodes.values() if n["type"] != "project"), key=lambda n: -deg.get(n["id"], 0))[:14]
        slim = lambda n: {"id": n["id"], "type": n["type"], "title": n["title"], "links": deg.get(n["id"], 0)}   # noqa: E731
        return {"stats": graph.stats(), "projects": [slim(n) for n in nodes.values() if n["type"] == "project"],
                "hubs": [slim(n) for n in hubs if deg.get(n["id"])]}

    def graph_node(self, node_id):
        from .graph import graph

        nodes, _ = graph.build()
        n = nodes.get(str(node_id))
        if not n:
            return None
        keep = ("id", "type", "title", "text", "ts", "project", "status", "path", "zone")
        return {"node": {k: n.get(k) for k in keep},
                "near": [{"id": x["node"]["id"], "type": x["node"]["type"], "title": x["node"]["title"], "kind": x["kind"],
                          "why": x["why"]} for x in graph.neighbors(n["id"])[:60]]}

    def graph_search(self, query):
        from .graph import graph

        return [{"id": n["id"], "type": n["type"], "title": n["title"]} for n in graph.find(str(query), 12)]

    def graph_timeline(self, node_id="", days=0):
        from .graph import graph

        ev = graph.timeline(query=str(node_id) or None, days=int(days) or None, limit=120)
        return [{"ts": e["ts"], "what": e["what"], "id": e["node"]["id"], "type": e["node"]["type"], "title": e["node"]["title"]} for e in ev]

    def graph_unlink(self, a, b):
        from .graph import graph

        return graph.unlink(str(a), str(b))

    # подключения: реестр, проверка, выключить/включить, забыть
    def connectors_get(self, deep=False):
        from . import connectors

        return connectors.overview(deep=bool(deep))

    def connector_set(self, cid, on):
        from . import connectors

        return connectors.set_on(str(cid), bool(on))

    def connector_forget(self, cid):
        from . import connectors

        c = connectors.BY_ID.get(str(cid))
        return c.forget() if c and c.can_forget else "нечего забывать"

    # большие цели
    def goals_list(self):
        from .goals import goals

        goals.sync_tasks()
        return goals.all()

    def goal_step_set(self, sid, status):
        from .goals import goals

        return goals.set_step(int(sid), str(status))

    # визуальная память: галерея и поиск
    def visual_search(self, query="", limit=40):
        import base64 as b64

        from . import visual as vm

        out = []
        for r in vm.visual.search(str(query or ""), limit=int(limit or 40)):
            full = vm.visual.get(r["id"], thumb=True)
            out.append(dict(r, thumb="data:image/jpeg;base64," + b64.standard_b64encode(full["thumb"]).decode() if full and full["thumb"] else "",
                            source_name=vm.SOURCES.get(r["source"], r["source"])))
        return {"items": out, "stats": vm.visual.stats()}

    def visual_open(self, vid):
        from . import visual as vm
        from .tools.pics import open_item

        item = vm.visual.get(int(vid))
        return open_item(item) if item else None

    def visual_forget(self, vid):
        from . import visual as vm

        return vm.visual.forget(int(vid))

    # подсказки
    def proactive_get(self):
        from . import proactive

        return {"mode": proactive.mode(), "modes": proactive.MODES, "tips": proactive.collect()}

    def proactive_set_mode(self, m):
        from . import proactive

        return proactive.set_mode(str(m))

    def proactive_dismiss(self, key):
        from . import proactive

        proactive.snooze(str(key))
        return True

    # автоматизации
    def workflows_list(self):
        from .workflows import workflows

        return {"items": workflows.all(), "runs": workflows.runs(limit=30)}

    def workflow_enable(self, wid, on):
        from .workflows import workflows

        return workflows.set_enabled(int(wid), bool(on))

    # Action Center и безопасный режим
    def action_center(self):
        from . import actions

        return actions.overview()

    def safe_mode_set(self, on):
        from . import safemode

        return {"on": safemode.on(), "done": safemode.enable("кнопка в окне") if on else safemode.disable()}

    def answer_pending(self, yes):
        """Ответ на вопрос «да/нет» кнопкой в окне — как будто сказан голосом."""
        commands.put(Typed("да" if yes else "нет", "local"))
        return True

    # мир: события для глобуса, рынки, киберугрозы
    def world_get(self, fresh=False):
        from . import world

        return world.picture(fresh=bool(fresh))

    def world_source(self, name, on):
        from . import world

        world.set_source(str(name), bool(on))
        return world.picture()

    # самочувствие: быстрая проверка без сети (каждые полминуты) или глубокая — настоящими запросами (кнопка)
    def system_health(self, deep=False):
        from . import system_state as ss

        items = ss.deep() if deep else ss.quick()
        if deep:
            ss.save(items)
        level, summary = ss.verdict(items)
        return {"level": level, "summary": summary, "items": items, "deep": bool(deep), "at": time.time()}

    # постоянное зрение: включить и выключить из окна
    def vision_get(self):
        return {"on": vision.enabled, "title": "" if vision.private else vision.title[:80], "private": vision.private}

    def vision_set(self, on):
        vision.set_enabled(bool(on))
        if on:
            vision.start()
        brain.js("chloeSee", vision.title[:80] if on and not vision.private else "", vision.private, vision.enabled)
        return vision.enabled

    def city_get(self):
        c = settings.get("city")
        return place_text(c) if c else ""

    def city_set(self, name):
        name = str(name).strip()
        if not name:
            return {"ok": False, "text": "Напишите город."}
        try:
            place = find_city(name)
        except Exception as e:
            return {"ok": False, "text": "Нет связи с сервером погоды: " + str(e)}
        if place is None:
            return {"ok": False, "text": "Не нашла «" + name + "»."}
        settings.set("city", place)
        journal.add("memory", "Погода", "Вы указали город: " + place_text(place), {"city": place, "by": "окно"})
        return {"ok": True, "text": place_text(place)}

    def memory_delete(self, mid):
        m = forget_memory(int(mid))
        if m is None:
            return False
        journal.add("memory", "Память", "Вы удалили: " + m["text"], {"id": m["id"], "text": m["text"], "by": "окно"})
        return True


def serve_ui():
    """Локальный сервер для страницы мозга (только для этого компьютера)."""

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(UI_DIR), **kw)

        def log_message(self, *a):
            pass

    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return "http://127.0.0.1:{}/chloe-mind.html?app=1".format(httpd.server_address[1])


def install_voice(name):
    """Скачивает модель Piper в ~/.chloe/voices. Список голосов: python -m piper.download_voices"""
    import pathlib

    from piper.download_voices import download_voice

    config.VOICES_DIR.mkdir(parents=True, exist_ok=True)
    print("Скачиваю голос {} в {} …".format(name, config.VOICES_DIR))
    download_voice(name, pathlib.Path(config.VOICES_DIR))
    print("Готово. Чтобы говорить им, задайте CHLOE_PIPER_VOICE={}, если он не основной.".format(name))


def main():
    parser = argparse.ArgumentParser(description="Chloe — голосовой ассистент")
    parser.add_argument("--text", action="store_true", help="без микрофона: команды с клавиатуры")
    parser.add_argument("--no-window", action="store_true", help="без окна с мозгом")
    parser.add_argument("--fullscreen", action="store_true", help="мозг на весь экран")
    parser.add_argument("--install-voice", nargs="?", const=config.PIPER_VOICE, metavar="ГОЛОС",
                        help="скачать офлайн-голос Piper (по умолчанию {}, ~60 МБ) и выйти".format(config.PIPER_VOICE))
    parser.add_argument("--add-skill", metavar="ПАПКА_ИЛИ_GIT",
                        help="добавить навык Claude (папка с SKILL.md или git-репозиторий с навыками) в ~/.chloe/skills и выйти")
    parser.add_argument("--restore", nargs="?", const="", metavar="ДЕНЬ",
                        help="вернуть мозг и память из копии (без дня — список копий) и выйти")
    parser.add_argument("--new-phone-key", action="store_true", help="новый код для телефона (старые телефоны отключатся) и выйти")
    parser.add_argument("--install-ears", action="store_true",
                        help="скачать офлайн-слух Vosk для слова «Хлоя» (~45 МБ) и выйти")
    parser.add_argument("--login-telegram", action="store_true",
                        help="один раз войти в Telegram (api_id, api_hash, телефон и код вводите сами) и выйти")
    parser.add_argument("--autostart", choices=["on", "off", "status"],
                        help="запускать Chloe вместе с компьютером (после входа в систему): on / off / status — и выйти")
    args = parser.parse_args()
    if args.autostart:
        from . import autostart

        if args.autostart == "on":
            print("Автозапуск включён:", autostart.enable())
        elif args.autostart == "off":
            print("Автозапуск выключен." if autostart.disable() else "Автозапуск и не был включён.")
        else:
            print("Автозапуск включён." if autostart.enabled() else "Автозапуск выключен.")
        return
    if args.login_telegram:
        from .telegram import login as telegram_login

        telegram_login()
        return
    if args.restore is not None:
        if not args.restore:
            print("Копии мозга и памяти:", ", ".join(snapshots.days()) or "пока нет")
            print("Вернуть: python run.py --restore ДЕНЬ (при закрытой Chloe)")
        else:
            print("Вернула:", ", ".join(snapshots.restore(args.restore)), "— текущие сохранены как «перед-восстановлением».")
        return
    if args.new_phone_key:
        remote.new_key()
        print("Новый код создан: откройте в окне Chloe кнопку «Телефон» и отсканируйте QR-код заново.")
        return
    if args.add_skill:
        names = skillbook.add(args.add_skill)
        print("Добавлены навыки ({}): {}. Chloe увидит их при следующей просьбе.".format(len(names), ", ".join(names)))
        return
    if args.install_ears:
        ears_install()
        return
    if args.install_voice:
        install_voice(args.install_voice)
        return
    from . import autostart

    if not autostart.single_instance():
        print("Chloe уже работает — вторая копия не нужна (обе слушали бы микрофон). Выхожу.")
        return
    voice.enabled = not args.text
    if voice.enabled:
        if config.TTS in ("piper", "edge"):   # Ирина нужна только там, где она основной или запасной голос
            threading.Thread(target=voice.load_piper, daemon=True).start()   # модель голоса грузится, пока открывается окно
        if config.WAKE_OFFLINE:
            threading.Thread(target=ears.load, daemon=True).start()

    snapshots.daily()   # копия мозга и памяти за сегодня
    api = Api()
    remote.start(api)   # телефон-пульт (в той же Wi-Fi сети); работает и без окна на компьютере

    if args.no_window:
        assistant(args)
        return

    import webview

    def on_loaded():
        # ждём, пока мозг загрузится из файла, и только потом доращиваем недостающие навыки
        def wait_ready():
            for _ in range(100):
                try:
                    if window.evaluate_js("window.chloeReady === true"):
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            brain.resume()   # и показать события, пришедшие, пока окно грузилось
            for name, desc, zone in {v[0]: v for v in SKILLS.values() if v[1]}.values():
                brain.ensure(name, desc, zone)
            for s in skillbook.all_skills():   # навыки Claude — тоже нейроны
                brain.ensure(s["name"], s["description"][:200], "Навыки")
        threading.Thread(target=wait_ready, daemon=True).start()

    window = webview.create_window("Chloe", serve_ui(), js_api=api, width=520, height=900,
                                   background_color="#04101a", fullscreen=args.fullscreen)
    brain.window = window
    window.events.loaded += on_loaded
    window.events.before_load += brain.pause   # перезагрузка окна (после «забудь») — события ждут, а не теряются
    threading.Thread(target=assistant, args=(args,), daemon=True).start()
    webview.start(private_mode=False, storage_path=str(DATA / "webview"))
    os._exit(0)
