"""Два мозга: быстрый для простого, сильный для сложного, переключение по ходу задачи."""
import types
import unittest

from chloe import config
from chloe.journal import journal
from chloe.signals import interrupt
from chloe.thinking import think
from chloe.thinking.router import Route
from chloe.voice import voice

voice.enabled = False


class RouteTest(unittest.TestCase):
    def setUp(self):
        config.PROVIDER = "anthropic"
        config.MODEL_FAST, config.MODEL_STRONG = "fast-model", "strong-model"

    def test_simple_request_starts_fast(self):
        for text in ("который час", "открой YouTube", "расскажи сказку", "какая завтра погода"):
            self.assertEqual(Route(text).model, "fast-model", text)

    def test_hard_words_start_strong(self):
        for text in ("что у меня на экране", "перемести PDF в папку Отчёты", "скачай VLC",
                     "удали старые скриншоты", "напиши письмо начальнику", "выполни команду"):
            self.assertEqual(Route(text).model, "strong-model", text)

    def test_hard_tool_hands_step_to_strong(self):
        r = Route("открой сайт")
        self.assertFalse(r.redo_for(["open_url"]))
        self.assertTrue(r.redo_for(["screenshot"]))
        self.assertEqual(r.model, "strong-model")
        self.assertFalse(r.redo_for(["mouse_click"]))   # сильный уже думает — повторять нечего

    def test_error_or_many_steps_switch_to_strong(self):
        r = Route("найди")
        r.after_step(failed=True)
        self.assertEqual(r.model, "strong-model")
        r = Route("найди")
        for _ in range(3):
            r.after_step(failed=False)
        self.assertEqual(r.model, "strong-model")

    def test_one_model_means_no_switching(self):
        config.MODEL_FAST = config.MODEL_STRONG = "only-model"
        r = Route("перемести файлы")
        self.assertFalse(r.redo_for(["screenshot"]))
        self.assertEqual(r.model, "only-model")


def block(**kw):
    return types.SimpleNamespace(**kw)


class FakeClaude:
    """Быстрая модель хочет скриншот (сложно), сильная делает скриншот и отвечает."""
    def __init__(self):
        self.models = []
        self.messages = self

    def create(self, model, **kw):
        self.models.append(model)
        if len(self.models) == 1:
            return block(stop_reason="tool_use", content=[block(type="tool_use", id="fast1", name="screenshot", input={})])
        if len(self.models) == 2:
            return block(stop_reason="tool_use", content=[block(type="tool_use", id="strong1", name="system_info", input={})])
        return block(stop_reason="end_turn", content=[block(type="text", text="Готово")])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        config.PROVIDER = "anthropic"
        config.MODEL_FAST, config.MODEL_STRONG = "fast-model", "strong-model"
        interrupt.clear()

    def test_strong_redoes_the_step_fast_started(self):
        fake, msgs = FakeClaude(), []
        self.assertEqual(think(fake, msgs, "посмотри, что открыто"), "Готово")
        self.assertEqual(fake.models, ["fast-model", "strong-model", "strong-model"])
        used = [b.id for m in msgs if m["role"] == "assistant" for b in m["content"] if getattr(b, "type", "") == "tool_use"]
        self.assertEqual(used, ["strong1"])   # скриншот быстрого мозга не выполнялся и в историю не попал
        self.assertTrue(any(e["kind"] == "brain" for e in journal.list()))   # переключение видно в журнале


class Scripted:
    """Отвечает по сценарию: список ответов по очереди; запоминает, какой моделью и с какими сообщениями спрашивали."""
    def __init__(self, *answers):
        self.answers, self.models, self.seen = list(answers), [], []
        self.messages = self

    def create(self, model, messages, **kw):
        self.models.append(model)
        self.seen.append(messages[-1])
        kind, value = self.answers.pop(0)
        if kind == "tool":
            return block(stop_reason="tool_use", content=[block(type="tool_use", id="t%d" % len(self.models), name=value, input={})])
        return block(stop_reason="end_turn", content=[block(type="text", text=value)])


class AnswerWithoutAction(unittest.TestCase):
    def setUp(self):
        config.PROVIDER = "anthropic"
        config.MODEL_FAST, config.MODEL_STRONG = "fast-model", "strong-model"
        interrupt.clear()

    def test_fast_lie_is_redone_by_strong(self):
        fake = Scripted(("text", "Закрываю браузер."), ("tool", "system_info"), ("text", "Готово, закрыла."))
        msgs = []
        self.assertEqual(think(fake, msgs, "закрой браузер"), "Готово, закрыла.")
        self.assertEqual(fake.models, ["fast-model", "strong-model", "strong-model"])
        said = [b.text for m in msgs if m["role"] == "assistant" for b in m["content"] if getattr(b, "type", "") == "text"]
        self.assertNotIn("Закрываю браузер.", said)   # ложный ответ не озвучен и в историю не попал

    def test_strong_gets_one_reminder(self):
        config.MODEL_FAST = config.MODEL_STRONG = "only-model"
        fake = Scripted(("text", "Открыла папку."), ("tool", "system_info"), ("text", "Открыла."))
        self.assertEqual(think(fake, [], "открой папку загрузки"), "Открыла.")
        self.assertIn("не вызвала ни одного инструмента", fake.seen[1]["content"][0]["text"])

    def test_honest_no_after_reminder_is_accepted(self):
        config.MODEL_FAST = config.MODEL_STRONG = "only-model"
        fake = Scripted(("text", "Включила подсветку."), ("text", "Пока не умею менять подсветку клавиатуры."))
        self.assertEqual(think(fake, [], "включи подсветку клавиатуры"), "Пока не умею менять подсветку клавиатуры.")
        self.assertEqual(len(fake.models), 2)   # напоминание одно — без бесконечного цикла

    def test_chat_stays_fast(self):
        fake = Scripted(("text", "Колобок ушёл от бабушки."))
        self.assertEqual(think(fake, [], "расскажи сказку"), "Колобок ушёл от бабушки.")
        self.assertEqual(fake.models, ["fast-model"])

    def test_after_a_tool_the_answer_is_trusted(self):
        fake = Scripted(("tool", "system_info"), ("text", "Готово."))
        self.assertEqual(think(fake, [], "открой сайт"), "Готово.")
        self.assertEqual(fake.models, ["fast-model", "fast-model"])

    def test_checked_without_checking_is_redone(self):
        """Живой случай 10.11.2026: «Проверь проект» — быстрая модель ответила «Проверила проект…» с выдуманными цифрами, не вызвав инструмент."""
        fake = Scripted(("text", "Проверила проект, босс. Открыто 6 задач."), ("tool", "system_info"), ("text", "Проверила: открыто 5 задач."))
        self.assertEqual(think(fake, [], "проверь проект Хлоя"), "Проверила: открыто 5 задач.")
        self.assertEqual(fake.models, ["fast-model", "strong-model", "strong-model"])

    def test_claims_vocabulary(self):
        from chloe.thinking.router import ACTIONS, CLAIMS

        for text in ("Проверила проект.", "Нашла три файла.", "Прочитала письмо.", "Записала в заметки.", "Изучила вопрос."):
            self.assertTrue(CLAIMS.search(text), text)
        for text in ("Не нашла такого файла.", "Не проверила: нет сети.", "Колобок ушёл от бабушки.", "Сегодня дождь."):
            self.assertFalse(CLAIMS.search(text), text)                 # честное «не получилось» — не заявление о сделанном
        for text in ("проверь проект", "посмотри, что нового", "изучи вопрос", "найди рецепт плова"):
            self.assertTrue(ACTIONS.search(text), text)
        for text in ("расскажи сказку", "как дела", "который час"):
            self.assertFalse(ACTIONS.search(text), text)

    def test_power_lie_is_redone(self):
        fake = Scripted(("text", "Выключаю компьютер."), ("tool", "system_info"), ("text", "Выключаю."))
        think(fake, [], "выключи компьютер")
        self.assertEqual(fake.models, ["fast-model", "strong-model", "strong-model"])


if __name__ == "__main__":
    unittest.main()
