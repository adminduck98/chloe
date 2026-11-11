"""Над чем работает пользователь: проект, программа, файл, минуты — из истории окон."""
import unittest

from chloe import focus as F

NOW = 100000.0


def rows(*pairs):
    """(минут назад, заголовок) → [(время, заголовок)] по порядку."""
    return [(NOW - m * 60, t) for m, t in pairs]


class Summary(unittest.TestCase):
    def test_project_app_file_and_minutes(self):
        r = rows((50, "YouTube — Brave"), (40, "app.py — chloe-main — Visual Studio Code"),
                 (10, "duck@duck-HP: ~/chloe-main"), (5, "voice.py — chloe-main — Visual Studio Code"))
        s = F.summary(r, NOW, ["chloe", "стиковые ролики"])
        self.assertIn("проект «chloe» — 40 мин", s)                  # VS Code 30 + терминал в папке проекта 5 + VS Code 5
        self.assertIn("сейчас VS Code, файл voice.py (5 мин)", s)
        self.assertIn("Brave 10 мин", s)

    def test_private_windows_and_chloe_itself_do_not_count(self):
        r = rows((30, "Вход — Сбербанк — Brave"), (20, "Chloe"), (19, "notes.md — Visual Studio Code"))
        s = F.summary(r, NOW, [], private=lambda t: "Сбербанк" in t)
        self.assertNotIn("Сбербанк", s)
        self.assertNotIn("Brave", s)
        self.assertIn("файл notes.md", s)

    def test_too_little_work_gives_nothing(self):
        self.assertEqual(F.summary(rows((1, "x — Brave")), NOW, []), "")
        self.assertEqual(F.summary([], NOW, []), "")

    def test_only_last_hour(self):
        r = rows((180, "old.py — chloe-main — Visual Studio Code"), (30, "YouTube — Brave"))
        s = F.summary(r, NOW, ["chloe"])
        self.assertIn("проект «chloe» — 30 мин", s)                  # из трёх часов — только последний час
        self.assertIn("сейчас Brave", s)

    def test_app_and_file_names(self):
        self.assertEqual(F.app_of("duck@host: ~/x"), "Терминал")
        self.assertEqual(F.app_of("Отчёт — LibreOffice Writer"), "LibreOffice")
        self.assertEqual(F.file_of("Глава 2.docx — LibreOffice"), "2.docx")
        self.assertEqual(F.project_of("duck@h: ~/projects/chloe-main", ["chloe"]), "chloe")


class Tool(unittest.TestCase):
    def test_vision_focus(self):
        from unittest import mock

        from chloe import vision as V

        v = V.Vision(capture=lambda: None, title_of=lambda: "", clock=lambda: NOW)
        v.history.extend(rows((20, "app.py — chloe-main — Visual Studio Code")))
        with mock.patch.object(V.Vision, "enabled", True), mock.patch.object(V, "vision", v), \
                mock.patch.object(V.Vision, "private_words", lambda self: []):
            out = V.tool_vision({"action": "focus"})
        self.assertIn("файл app.py (20 мин)", out)


if __name__ == "__main__":
    unittest.main()
