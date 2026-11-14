"""Кому сказано: «Хлоя» — всегда ей (что бы ни было открыто); без «Хлоя» — только ответ на её вопрос."""
import unittest
from unittest import mock

from chloe import addressee
from chloe.addressee import followup_for_chloe, window_open_for


class Followup(unittest.TestCase):
    def test_answer_to_her_question_is_hers_in_any_window(self):
        self.assertTrue(followup_for_chloe("да", "Открыть?", "Claude")[0])
        self.assertTrue(followup_for_chloe("Ummon", "Какую музыку, босс?", "Telegram")[0])
        self.assertTrue(window_open_for("Скачать «Дюну» 2021 или вторую часть?"))

    def test_casual_speech_without_name_is_not_hers(self):
        ok, why = followup_for_chloe("а завтра", "Сегодня +12, ясно.", "Chloe")
        self.assertFalse(ok)
        self.assertIn("ничего не спрашивала", why)
        self.assertFalse(window_open_for("Добрый вечер, босс! Слушаю."))     # после приветствия — только по имени

    def test_old_behaviour_switch(self):
        with mock.patch.object(addressee, "MODE", "all"):
            self.assertTrue(followup_for_chloe("а завтра", "Сегодня +12, ясно.", "Claude")[0])
            self.assertTrue(window_open_for("Готово."))


if __name__ == "__main__":
    unittest.main()
