"""Безопасность: подтверждение «да/нет», слово «Хлоя», опасные пути и обход отказа."""
import unittest
from unittest import mock

from chloe import config
from chloe.app import strip_wake
from chloe.tools import run_tool
from chloe.tools.files import tool_delete_path
from chloe.tools.paths import P, is_sensitive
from chloe.tools.system import tool_open_app
from chloe.voice import voice

voice.enabled = False   # подтверждение с клавиатуры, а не голосом


def answer(text):
    with mock.patch("builtins.input", return_value=text):
        return voice.ask_yes_no("Сделать?")


class YesNo(unittest.TestCase):
    def test_yes(self):
        for text in ("да", "да, делай", "ок", "давай"):
            self.assertTrue(answer(text), text)

    def test_not_yes_by_accident(self):
        # раньше «да» искалось как кусок слова: «удали», «когда», «около» считались согласием
        for text in ("удали только pdf", "когда закончишь", "около того", "нет", "не надо", "да нет наверное"):
            self.assertFalse(answer(text), text)


class Wake(unittest.TestCase):
    def test_wake_word_only_as_whole_word(self):
        self.assertEqual(strip_wake("Хлоя, скачай VLC"), ("скачай VLC", True))
        self.assertTrue(strip_wake("слушай, Хлоя, который час")[1])
        for text in ("включи клоуна", "поклонник пришёл"):
            self.assertFalse(strip_wake(text)[1], text)

    def test_misheard_name_still_counts(self):
        """Распознавание искажает имя: «Хлоа», «Клои», «Хло» — всё равно обращаются к ней."""
        self.assertEqual(strip_wake("Хлоа, какая погода"), ("какая погода", True))
        self.assertEqual(strip_wake("Клои привет"), ("привет", True))
        self.assertTrue(strip_wake("скажи, хло, который час")[1])
        for text in ("хлоп в ладоши", "хлор в воде", "клон овцы", "хлопья на завтрак", "слоя краски"):
            self.assertFalse(strip_wake(text)[1], text)


class Paths(unittest.TestCase):
    def test_sensitive(self):
        for path in ("~/.config/autostart/x.desktop", "~/.bashrc", "/etc/x.conf", "~/run.sh"):
            self.assertTrue(is_sensitive(P(path)), path)
        self.assertFalse(is_sensitive(P("~/Документы/отчёт.txt")))

    def test_protected_folders_cannot_be_deleted(self):
        for path in (str(config.DOWNLOADS), str(config.HOME), str(config.DOCUMENTS) + "/../"):
            config.DOWNLOADS.mkdir(parents=True, exist_ok=True)
            config.DOCUMENTS.mkdir(parents=True, exist_ok=True)
            self.assertTrue(tool_delete_path({"path": path}).startswith("Отказано"), path)

    def test_open_app_rejects_shell_tricks(self):
        self.assertTrue(tool_open_app({"name": "notepad&calc"}).startswith("Недопустимое"))


class Declined(unittest.TestCase):
    def test_no_means_no_and_no_workaround(self):
        with mock.patch("builtins.input", return_value="нет"):
            out, _, failed = run_tool("run_command", {"command": "echo hi"})
        self.assertTrue(failed)
        self.assertIn("Не делай этого", out)   # модели прямо запрещено добиться того же другим способом

    def test_yes_runs(self):
        with mock.patch("builtins.input", return_value="да, делай"):
            out, _, failed = run_tool("run_command", {"command": "echo hi"})
        self.assertFalse(failed)
        self.assertIn("hi", out)


class ReadOnlyCommands(unittest.TestCase):
    def test_only_looking_runs_without_asking(self):
        from chloe.tools.system import read_only
        for cmd in ("xdg-settings get default-web-browser", "ls -la", "df -h", "gsettings get org.gnome.desktop.interface gtk-theme",
                    "pactl get-sink-volume @DEFAULT_SINK@", "systemctl --user status pipewire", "date"):
            self.assertTrue(read_only(cmd), cmd)

    def test_anything_that_changes_or_chains_still_asks(self):
        from chloe.tools.system import read_only
        for cmd in ("xdg-settings set default-web-browser brave-browser.desktop", "gsettings set a b c", "rm -rf ~",
                    "ls; rm -rf ~", "ls && reboot", "ls | sh", "ls > /etc/passwd", "ls $(reboot)", "ls `reboot`",
                    "date -s 2020-01-01", "systemctl stop ssh", "pactl set-sink-volume 0 10%", "echo hi", "sudo ls",
                    "xdg-settings", "ls\nreboot", "ls 'unclosed"):
            self.assertFalse(read_only(cmd), cmd)

    def test_read_only_runs_without_input(self):
        with mock.patch("builtins.input", side_effect=AssertionError("не должна спрашивать")):
            out, _, failed = run_tool("run_command", {"command": "pwd"})
        self.assertFalse(failed)
        self.assertIn("Код 0", out)


if __name__ == "__main__":
    unittest.main()
