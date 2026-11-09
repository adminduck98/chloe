"""Мост к окну с мозгом: каждое действие Chloe загорается там нейроном. Без окна ничего не делает."""
import json

from .remote import events as remote_events


class Brain:
    """Передаёт действия Chloe в окно с мозгом. Без окна ничего не делает."""

    def __init__(self):
        self.window = None
        self.ready = False
        self.last = None

    def js(self, fn, *args):
        remote_events.push(fn, list(args))   # телефоны-пульты видят то же, что окно
        if not self.window or not self.ready:
            return
        # только ASCII: pywebview на Linux меряет длину скрипта в символах, а WebKit — в байтах, и кириллица обрезает скрипт
        call = "window.{0} && window.{0}({1})".format(fn, ", ".join(json.dumps(a) for a in args))
        try:
            self.window.evaluate_js(call)
        except Exception:
            pass

    def state(self, name):
        self.js("chloeState", name)

    def heard(self, text):
        self.js("chloeHeard", text)

    def reply(self, text):
        self.js("chloeReply", text)

    def voice(self, level, who="user"):
        self.js("chloeVoice", level, who)

    def use(self, skill):
        """Навык начал работать: вспышка и свечение, пока шаг не закончится."""
        self.js("chloeUse", skill)
        self.last = skill

    def task(self):
        """Новая просьба: цепочка навыков начинается заново."""
        self.js("chloeTask")

    def step(self, skill, seconds, ok, things):
        """Шаг закончился: связь с прошлым навыком крепнет, сигнал идёт столько, сколько шёл шаг,
        предметы из мира пользователя (программы, сайты, папки) прорастают нейронами, ошибка оставляет шрам."""
        self.js("chloeStep", skill, round(seconds, 2), bool(ok), things)

    def recall(self, text):
        """Воспоминание пригодилось в ответе — загорается зелёным."""
        self.js("chloeRecall", text)

    def replay(self, title, steps):
        self.js("chloeReplay", title, steps)

    def error(self, skill, why):
        self.js("chloeError", skill, why[:120])

    def success(self):
        self.js("chloeSuccess")

    def ensure(self, name, desc, zone):
        self.js("chloeEnsure", name, "skill", desc, zone)

    def remember(self, text, zone):
        self.js("chloeRemember", text, zone)


brain = Brain()
