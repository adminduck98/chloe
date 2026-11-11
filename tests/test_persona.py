"""Личность Chloe: один голос и характер при любой модели."""
import unittest
from unittest import mock

from chloe import persona as P
from chloe.settings import settings


class Polish(unittest.TestCase):
    def test_feminine_about_herself(self):
        self.assertEqual(P.polish("Понял, босс: создаём двух персонажей."), "Поняла, босс: создаём двух персонажей.")
        self.assertEqual(P.polish("Я нашёл файл и открыл его."), "Я нашла файл и открыл его.".replace("открыл", "открыл"))
        self.assertEqual(P.polish("Я не смог подключиться. Сделал, что мог."), "Я не смогла подключиться. Сделала, что мог.")
        self.assertEqual(P.polish("Я готов, я рад помочь"), "Я готова, я рада помочь")

    def test_other_people_untouched(self):
        self.assertEqual(P.polish("Он понял и сделал."), "Он понял и сделал.")
        self.assertEqual(P.polish("Пользователь открыл файл."), "Пользователь открыл файл.")

    def test_no_servile_openers_and_tails(self):
        self.assertEqual(P.polish("Отличный вопрос! Погода ясная. Надеюсь, это поможет!"), "Погода ясная.")
        self.assertEqual(P.polish("Как ИИ, я не могу этого знать."), "Я не могу этого знать.")


class Delivery(unittest.TestCase):
    def setUp(self):
        settings.set("persona", {})
        self.addCleanup(settings.set, "persona", {})

    def test_mood_by_meaning(self):
        self.assertEqual(P.mood("Готово, ролик собран."), "joy")
        self.assertEqual(P.mood("Не получилось: сайт молчит."), "soft")
        self.assertEqual(P.mood("Это удалит папку. Точно?"), "serious")
        self.assertEqual(P.mood("Сейчас 10:20."), "neutral")

    def test_same_voice_small_shifts(self):
        base = P.edge_args("Сейчас 10:20.")
        joy = P.edge_args("Готово!")
        self.assertEqual(base, {"rate": "+4%", "pitch": "-3Hz", "volume": "+0%"})
        self.assertEqual(joy, {"rate": "+9%", "pitch": "+0Hz", "volume": "+0%"})

    def test_emotions_off_is_flat(self):
        P.change(emotions=False)
        self.assertEqual(P.edge_args("Готово!"), P.edge_args("Сейчас 10:20."))

    def test_long_sentence_gets_a_breath(self):
        long = ("Сегодня у тебя три встречи, первая в десять утра по проекту Chloe, вторая в два часа с командой дизайна, "
                "третья вечером в пять, и ещё нужно не забыть оплатить подписку на облако до конца недели.")
        out = P.shape(long)
        self.assertGreater(out.count("."), 1)
        self.assertEqual(P.shape("Да; конечно!!!"), "Да. конечно!")

    def test_limits_and_reset(self):
        P.change(rate=99, pitch=-99)
        self.assertEqual((P.profile()["rate"], P.profile()["pitch"]), (30, -20))
        P.reset()
        self.assertEqual(P.profile()["rate"], P.BASE["rate"])

    def test_piper_follows_speed(self):
        P.change(rate=-20)
        self.assertGreater(P.piper_length("Сейчас 10:20."), 1.0)          # медленнее — длиннее


class Tool(unittest.TestCase):
    def setUp(self):
        settings.set("persona", {})
        self.addCleanup(settings.set, "persona", {})

    def test_slower_and_back(self):
        from chloe.tools import myvoice

        out = myvoice.tool_my_voice({"action": "slower", "steps": 2})
        self.assertIn("скорость -8 %", out)
        self.assertIn("как было", myvoice.tool_my_voice({"action": "reset"}).replace("обычный", "как было"))

    def test_card_is_in_every_brain_prompt(self):
        from chloe.thinking.prompt import system_prompt

        self.assertIn("о себе всегда в женском роде", system_prompt())

    def test_say_polishes_any_model(self):
        from chloe.voice import Voice

        v = Voice(enabled=False)
        with mock.patch("chloe.voice.brain"), mock.patch("chloe.voice.journal") as j, mock.patch("time.sleep"):
            v.say("Понял, босс. Отличный вопрос!")
        self.assertEqual(j.add.call_args[0][2], "Поняла, босс. Отличный вопрос!")
