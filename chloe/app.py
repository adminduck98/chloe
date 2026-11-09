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
from .signals import busy, commands, heard_q, interrupt, is_stop, state
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


def assistant(args):
    if not config.has_key():
        voice.say("Не задан ключ: нужен DASHSCOPE_API_KEY (Qwen), DEEPSEEK_API_KEY, GEMINI_API_KEY или ANTHROPIC_API_KEY. "
                  "Я не могу думать без него.")
        return
    print("[мозг: {} · быстрый {} · сильный {}]".format(config.PROVIDER, config.MODEL_FAST, config.MODEL_STRONG))
    client = make_client()
    messages = []
    voice.say("Привет, я Хлоя. Слушаю.")
    state["listen_until"] = time.time() + ACTIVE_WINDOW
    if voice.enabled and not args.text:
        threading.Thread(target=recorder, daemon=True).start()
        threading.Thread(target=listener, daemon=True).start()
    threading.Thread(target=reminder_watcher, args=(voice.say,), daemon=True).start()
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
                command = typed
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
                heard = finish_speech(heard)   # дослушать до конца
                print("Вы:", heard)
                command, woke = strip_wake(heard)
                if not woke and time.time() > state["listen_until"]:
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

    def command(self, text):
        if busy.is_set() and is_stop(str(text)):   # «стоп» из строки ввода тоже перебивает
            interrupt.set()
            voice.stop_audio()
            return
        commands.put(str(text))

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
    args = parser.parse_args()
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
    voice.enabled = not args.text
    if voice.enabled:
        if config.TTS != "svetlana":   # в режиме «только Светлана» офлайн-голос не нужен
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
            brain.ready = True
            for name, desc, zone in {v[0]: v for v in SKILLS.values() if v[1]}.values():
                brain.ensure(name, desc, zone)
            for s in skillbook.all_skills():   # навыки Claude — тоже нейроны
                brain.ensure(s["name"], s["description"][:200], "Навыки")
        threading.Thread(target=wait_ready, daemon=True).start()

    window = webview.create_window("Chloe", serve_ui(), js_api=api, width=520, height=900,
                                   background_color="#04101a", fullscreen=args.fullscreen)
    brain.window = window
    window.events.loaded += on_loaded
    threading.Thread(target=assistant, args=(args,), daemon=True).start()
    webview.start(private_mode=False, storage_path=str(DATA / "webview"))
    os._exit(0)
