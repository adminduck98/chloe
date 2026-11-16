"""Правило владельца (16.11.2026): «попросил — значит, делай». Спрашивать только там, где теряются данные или
ослабляется защита; карта прав «спрашивать» — всегда (это его настройка)."""
import unittest
from unittest import mock

from chloe import config, voice


class Policy(unittest.TestCase):
    def test_delete_mode(self):
        with mock.patch.object(config, "CONFIRM", "delete"):
            for q in ("Отправить в Telegram маме: «Задержусь»?", "Мультик «Кофе»: 20 с. Делать?", "Скачать VLC?"):
                self.assertFalse(voice.must_ask(q), q)
            for q in ("Удалить 3 файла?", "Очистить корзину?", "Выключить компьютер?", "Закрыть все окна (5)?",
                      "Забыть: «кофе»?", "Ослабить защиту: экран?", "Выполнить команду: rm -rf ~/tmp?"):
                self.assertTrue(voice.must_ask(q), q)
            self.assertTrue(voice.must_ask("Отправить письмо?", force=True))

    def test_without_asking_is_logged_and_yes(self):
        with mock.patch.object(config, "CONFIRM", "delete"), mock.patch.object(voice.voice, "ask_yes_no") as ask:
            self.assertTrue(voice.confirm("Отправить в Telegram маме: «Задержусь»?"))
        ask.assert_not_called()

    def test_safe_and_off(self):
        with mock.patch.object(config, "CONFIRM", "safe"):
            self.assertTrue(voice.must_ask("Скачать VLC?"))
        with mock.patch.object(config, "CONFIRM", "off"):
            self.assertFalse(voice.must_ask("Удалить всё?"))


if __name__ == "__main__":
    unittest.main()
