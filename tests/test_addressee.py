"""Кому сказано: в окне после ответа без «Хлоя» Chloe не отвечает на диктовку другому помощнику, на созвон
и на длинную речь, если сама ничего не спрашивала."""
import unittest

from chloe.addressee import followup_for_chloe, other_app


class Followup(unittest.TestCase):
    def test_short_followup_is_for_her(self):
        self.assertTrue(followup_for_chloe("а завтра?", "Сегодня +12, ясно.", "Chloe")[0])
        self.assertTrue(followup_for_chloe("открой его", "Нашла файл отчёт.pdf.", "Исходный файл — Mozilla Firefox")[0])

    def test_dictating_to_claude_is_not(self):
        ok, why = followup_for_chloe("да", "Открыть?", "Claude")
        self.assertFalse(ok)
        self.assertIn("claude", why)

    def test_long_speech_without_her_question_is_not(self):
        text = "Вот это магнитный полюс то есть полюса которые двигались их верни и сделай более красивым"
        ok, why = followup_for_chloe(text, "Привет, босс, вечер на дворе. Готова.", "Firefox")
        self.assertFalse(ok)
        self.assertIn("длинная", why)

    def test_long_answer_to_her_question_is_for_her(self):
        text = "Нет давай лучше скачай вторую часть и положи её в папку с фильмами которую мы сделали вчера"
        self.assertTrue(followup_for_chloe(text, "Скачать «Дюну» 2021 или вторую часть?", "Firefox")[0])

    def test_calls_and_messengers(self):
        for title in ("Zoom Meeting", "Telegram", "‎⁨CholeAi⁩ – (74) Telegram", "Google Meet — Firefox"):
            self.assertTrue(other_app(title), title)
        self.assertEqual(other_app("Chloe"), "")                # её собственное окно
        self.assertEqual(other_app(""), "")


if __name__ == "__main__":
    unittest.main()
