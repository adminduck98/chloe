"""Мост к окну с мозгом: каждое действие Chloe загорается там нейроном. Без окна ничего не делает."""
import json

from .remote import events as remote_events


class Brain:
    """Передаёт действия Chloe в окно с мозгом. Без окна ничего не делает."""

    PENDING_MAX = 200   # столько событий окно может «догнать» после перезагрузки

    def __init__(self):
        self.window = None
        self.ready = False
        self.last = None
        self.pending = []   # события, пришедшие, пока окно грузилось: покажутся, когда оно будет готово

    def pause(self):
        """Окно начало (пере)загружаться — например, после «забудь»: события копим, а не шлём в пустую страницу."""
        self.ready = False

    def expect_reload(self, seconds=5.0):
        """Следующая команда перезагрузит окно («забудь»): копим события сразу, не дожидаясь, пока окно об этом скажет.
        Не перезагрузилось (нейрона не нашлось) — через seconds секунд продолжаем как обычно."""
        import threading

        self.pause()
        mark = self.reloads = getattr(self, "reloads", 0) + 1
        timer = threading.Timer(seconds, lambda: self.reloads == mark and not self.ready and self.resume())
        timer.daemon = True
        timer.start()

    def resume(self):
        """Окно готово: показываем всё, что накопилось, по порядку."""
        self.ready = True
        pending, self.pending = self.pending, []
        for call in pending:
            self._run(call)

    def js(self, fn, *args):
        remote_events.push(fn, list(args))   # телефоны-пульты видят то же, что окно
        if not self.window:
            return
        # только ASCII: pywebview на Linux меряет длину скрипта в символах, а WebKit — в байтах, и кириллица обрезает скрипт
        call = "window.{0} && window.{0}({1})".format(fn, ", ".join(json.dumps(a) for a in args))
        if not self.ready:
            self.pending = (self.pending + [call])[-self.PENDING_MAX:]
            return
        self._run(call)

    def _run(self, call):
        try:
            self.window.evaluate_js(call)
        except Exception:
            pass

    def state(self, name):
        self.js("chloeState", name)

    def heard(self, text):
        self.js("chloeHeard", text)

    def reply(self, text, where="local"):
        self.js("chloeReply", text, where)   # where: где ответ звучит — local (компьютер) или phone (телефон)

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
