"""Исправления по логу: самодельные адреса, статус плеера в Brave, напоминание при включении, медленный Qwen."""
import unittest
from unittest import mock

from chloe.signals import seen_text
from chloe.tools import HANDLERS, run_tool, url_allowed
from chloe.tools import desktop
from chloe.voice import voice

voice.enabled = False


class MadeUpAddresses(unittest.TestCase):
    def setUp(self):
        seen_text.clear()
        self.addCleanup(seen_text.clear)

    def test_homepages_always_open(self):
        for u in ("kinogo.style", "https://www.youtube.com/", "https://rutube.ru"):
            self.assertTrue(url_allowed(u), u)

    def test_made_up_page_is_refused_and_not_opened(self):
        opened = mock.Mock(return_value="Открыт сайт")
        with mock.patch.dict(HANDLERS, {"open_url": opened}):
            out, _, failed = run_tool("open_url", {"url": "https://kino.kz/search?q=Скрытые+фигуры"})
        opened.assert_not_called()
        self.assertTrue(failed)
        self.assertIn("web_search", out)

    def test_page_from_search_or_users_words_opens(self):
        seen_text.append("Скрытые фигуры (2016)\nhttps://rutube.ru/video/51e13fd815fa79915de83606b2f255dc/\nсмотреть")
        self.assertTrue(url_allowed("rutube.ru/video/51e13fd815fa79915de83606b2f255dc"))
        seen_text.append("открой github.com/adminduck98/chloe")             # назвал пользователь
        self.assertTrue(url_allowed("https://github.com/adminduck98/chloe"))
        self.assertFalse(url_allowed("https://kinogo.team/serials/7765-gravity-falls.html"))

    def test_search_results_are_remembered_by_run_tool(self):
        with mock.patch.dict(HANDLERS, {"web_search": lambda a: "Фильм\nhttps://example.org/film/42\nописание"}):
            run_tool("web_search", {"query": "фильм"})
        self.assertTrue(url_allowed("https://example.org/film/42"))


class MediaInBrave(unittest.TestCase):
    """На шине два «плеера»: Brave (играет фильм) и приложение Claude на Chromium (всегда остановлено, без трека)."""

    def bus(self, brave_status="Playing", brave=True):
        names = ["org.mpris.MediaPlayer2.chromium.instance17001"] + (["org.mpris.MediaPlayer2.brave.instance1"] if brave else [])

        def run(cmd, timeout=5, input_text=None):
            if "ListNames" in cmd[-1]:
                return "([" + ", ".join("'{}'".format(n) for n in ["org.freedesktop.DBus"] + names) + "],)"
            dest, prop = cmd[4], cmd[-1]
            claude = "chromium" in dest
            if prop == "PlaybackStatus":
                return "(<'Stopped'>,)" if claude else "(<'{}'>,)".format(brave_status)
            if prop == "Identity":
                return "(<'Claude'>,)" if claude else "(<'Brave'>,)"
            if prop == "Metadata":
                return "(@a{sv} {},)" if claude else "(<{'xesam:title': <'Синий трактор'>}>,)"
            return ""
        return mock.patch.object(desktop, "run", run)

    def test_status_names_brave_and_skips_claude(self):
        with self.bus(), mock.patch.object(desktop, "OS_NAME", "Linux"), mock.patch("shutil.which", return_value="/usr/bin/gdbus"):
            out = desktop.tool_media({"action": "status"})
        self.assertEqual(out, "Brave: играет — Синий трактор")

    def test_no_player_is_not_called_silence(self):
        with self.bus(brave=False), mock.patch.object(desktop, "OS_NAME", "Linux"), mock.patch("shutil.which", return_value="/usr/bin/gdbus"):
            out = desktop.tool_media({"action": "status"})
        self.assertIn("посмотри на экран", out)                       # не «ничего не играет»
        self.assertNotIn("Claude", out)


class StartupReminder(unittest.TestCase):
    def test_important_open_tasks_are_named(self):
        from chloe.app import startup_reminder
        from chloe.project_memory import project_memory

        with project_memory.lock:
            project_memory.db.execute("DELETE FROM proj_tasks")
            project_memory.db.commit()
        self.assertEqual(startup_reminder(), "")
        project_memory.add_task("chloe", "Сменить ключ DeepSeek", 1)
        project_memory.add_task("chloe", "Мелочь", 2)
        done = project_memory.add_task("chloe", "Уже сделано", 1)
        project_memory.set_status(done, "done")
        self.assertEqual(startup_reminder(), " Напоминаю важное: Сменить ключ DeepSeek.")


class SlowQwen(unittest.TestCase):
    def test_qwen_waits_at_most_15_seconds(self):
        from chloe.thinking import openai_chat as oc
        self.assertEqual(oc.PROVIDERS["qwen"]["timeout"], 15.0)


if __name__ == "__main__":
    unittest.main()
