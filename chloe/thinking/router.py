"""Два мозга: быстрый для простых просьб, сильный для сложных.

Каждая просьба начинается с быстрой модели. Сильная подключается сама:
- по словам просьбы сразу видно, что задача сложная (экран, файлы, скачать, команда, написать текст…);
- быстрая модель взялась за сложный инструмент — её ответ не выполняется, этот шаг заново делает сильная;
- шаг закончился ошибкой или шагов стало много — дальше думает сильная;
- ответ словами без действия («Выключаю компьютер», а инструмента не было) — не озвучивается:
  быстрый ответ переделывает сильная модель, а сильной один раз напоминаем сделать это инструментом.
"""
import re

from .. import config
from ..journal import journal

# инструменты, с которыми задача уже сложная: экран, мышь, клавиатура, терминал, изменение файлов, скачивание
HARD_TOOLS = {"screenshot", "mouse_click", "type_text", "press_keys", "scroll", "run_command",
              "download_file", "write_text_file", "move_path", "copy_path", "delete_path", "undo_change",
              "use_skill"}   # инструкции навыков бывают длинными — по ним работает сильный мозг
# экран, мышь и клавиатура: с «глазами» (config.MODEL_EYES) это их работа, а не сильного мозга
SCREEN_TOOLS = {"screenshot", "mouse_click", "type_text", "press_keys", "scroll"}
SCREEN_WORDS = re.compile(r"\b(экран|кликн|нажми|напечатай|введи|браузер|firefox|хром|chrome|сайт|страниц|вкладк|прокрут|"
                          r"листай|что видишь|посмотри)", re.IGNORECASE)
MAX_EYES_STEPS = 12
# пользователь учит: сценарий, навык, правило — это понимает сильный мозг (быстрый норовит сразу выполнять)
TEACH_WORDS = re.compile(r"(когда я (говорю|скажу)|если я (говорю|скажу)|запомни,? как|научись|выучи|впредь|"
                         r"неправильно|не так делай|надо было|всегда (открывай|делай|включай|отвечай)|никогда не (делай|открывай))",
                         re.IGNORECASE)
# слова в просьбе, с которыми сразу зовём сильный мозг
HARD_WORDS = re.compile(r"\b(экран|кликн|нажми|напечатай|введи|файл|папк|документ|скача|установи|удали|перемест|"
                        r"скопир|переимен|отмени|верни|команд|терминал|напиши (текст|письмо|код|сообщение)|составь|сравни|"
                        r"проанализ|разбер|придумай|програм|код\b)", re.IGNORECASE)
# просьба что-то сделать на компьютере — ответ без инструмента тут подозрителен
ACTIONS = re.compile(r"\b(выключи|включи|перезагрузи|закрой|открой|запусти|сверни|разверни|поставь|убавь|прибавь|"
                     r"громче|тише|ярче|темнее|скачай|создай|удали|перемести|скопируй|переименуй|отмени|найди файл|напиши|отправь|"
                     r"проверь|посмотри|изучи|проанализируй|узнай|прочитай|запиши|добавь|обнови|подготовь|найди|покажи|подключи|отключи)",
                     re.IGNORECASE)
# ответ, в котором она говорит, что делает или сделала
# «не нашла», «не проверила» — это честное «не получилось», а не заявление о сделанном: такие фразы не считаются
CLAIMS = re.compile(r"(?<!не\s)\b(выключаю|включаю|перезагружаю|закрываю|открываю|запускаю|сворачиваю|ставлю|убавляю|прибавляю|"
                    r"скачиваю|создаю|удаляю|перемещаю|копирую|выключила|включила|закрыла|открыла|запустила|"
                    r"поставила|скачала|создала|удалила|переместила|скопировала|сделала|готово|отправляю|отправила|написала|"
                    r"проверила|посмотрела|нашла|узнала|прочитала|изучила|проанализировала|записала|добавила|обновила|подготовила|"
                    r"поискала|сверила|разобрала|сохранила|изменила|исправила|настроила|подключила|отключила|отметила|составила)",
                    re.IGNORECASE)
NUDGE = ("Ты ответила, будто действуешь, но не вызвала ни одного инструмента — значит, на компьютере ничего не произошло. "
         "Сделай это инструментом, а если подходящего нет — честно скажи, что пока так не умеешь.")
MAX_FAST_STEPS = 3


def sees_images(model):
    """Умеет ли модель смотреть на картинки: DeepSeek — нет; Qwen, Claude, Gemini — да."""
    return bool(model) and not str(model).split("+")[0].startswith("deepseek")


class Route:
    """Какой моделью думать над этой просьбой сейчас."""

    def __init__(self, user_text):
        self.fast, self.strong = config.MODEL_FAST, config.MODEL_STRONG
        self.eyes = getattr(config, "MODEL_EYES", None)
        self.model = self.fast
        self.steps = 0
        self.text = user_text
        self.acted = False      # в этой просьбе уже вызывался инструмент
        self.nudged = False     # сильному мозгу уже напоминали
        hard = HARD_WORDS.search(user_text)
        screen = SCREEN_WORDS.search(user_text)
        teach = TEACH_WORDS.search(user_text)
        if self.fast == self.strong:
            self.model = self.strong
        elif teach:
            self.use_strong("учат: «{}»".format(teach.group(0)))
        elif self.eyes and (screen or hard) and (not hard or SCREEN_WORDS.match(hard.group(0))):
            self.use_eyes("в просьбе «{}»".format((screen or hard).group(0)))
        elif hard:
            self.use_strong("в просьбе «{}»".format(hard.group(0)))
        else:
            print("[быстрый мозг: {}]".format(self.fast))
        self.look_if_needed(user_text)

    def look_if_needed(self, user_text):
        """«Что это за ошибка?», «переведи вот это» — просьба про экран. Если выбранная модель картинок не видит
        (DeepSeek), отвечать вслепую нельзя: берёт модель с глазами."""
        from ..vision import SCREEN_HINT, vision

        if not (vision.enabled and SCREEN_HINT.search(user_text or "")) or sees_images(self.model):
            return
        if self.eyes and sees_images(self.eyes):
            self.use_eyes("просьба про экран, а «{}» картинок не видит".format(self.model))
        elif self.strong != self.model and sees_images(self.strong):
            self.use_strong("просьба про экран, а «{}» картинок не видит".format(self.model))

    @property
    def is_fast(self):
        return self.model == self.fast and self.fast != self.strong

    @property
    def is_eyes(self):
        return bool(self.eyes) and self.model == self.eyes

    def use_eyes(self, why):
        self.model = self.eyes
        print("[глаза: {} — {}]".format(self.eyes, why))
        journal.add("brain", "Мышление", "Глаза (экран): " + why, {"model": self.eyes, "why": why})

    def use_strong(self, why):
        self.model = self.strong
        print("[сильный мозг: {} — {}]".format(self.strong, why))
        journal.add("brain", "Мышление", "Сильный мозг: " + why, {"model": self.strong, "why": why})

    def redo_for(self, tool_names):
        """Быстрый мозг взялся за сложное: его ответ не выполняем, шаг заново сделает сильный. True — повторить шаг."""
        hard = set(tool_names) & HARD_TOOLS
        if self.is_fast and hard:
            if self.eyes and hard <= SCREEN_TOOLS:
                self.use_eyes("нужно " + ", ".join(sorted(hard)))
            else:
                self.use_strong("нужно " + ", ".join(sorted(hard)))
            return True
        if self.is_eyes and hard - SCREEN_TOOLS:   # команды, файлы, скачивание — это уже работа сильного
            self.use_strong("нужно " + ", ".join(sorted(hard - SCREEN_TOOLS)))
            return True
        return False

    def check_answer(self, answer):
        """Ответ словами без действия. "redo" — переделать этот шаг сильным мозгом (ответ не сохраняется);
        "nudge" — сохранить ответ и попросить сделать инструментом; None — ответ хороший."""
        if self.acted or self.nudged:
            return None
        claims = CLAIMS.search(answer or "")
        if not (claims or ACTIONS.search(self.text)):
            return None
        if self.is_fast or self.is_eyes:
            self.use_strong("ответ без действия: «{}»".format((answer or "")[:40]))
            return "redo"
        if claims:
            self.nudged = True
            print("[ответ без действия — напоминаю сделать инструментом]")
            journal.add("brain", "Мышление", "Ответ без действия: " + answer[:80], {"answer": answer})
            return "nudge"
        return None

    def after_step(self, failed):
        self.acted = True
        self.steps += 1
        if self.is_fast and (failed or self.steps >= MAX_FAST_STEPS):
            self.use_strong("ошибка в шаге" if failed else "больше {} шагов".format(MAX_FAST_STEPS))
        elif self.is_eyes and (failed or self.steps >= MAX_EYES_STEPS):
            self.use_strong("глаза ошиблись" if failed else "больше {} шагов на экране".format(MAX_EYES_STEPS))
