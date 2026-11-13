"""HolyArrs: ключ только в заголовке, ответы без картинок и ссылок, запрос фильма — только после «да». Сеть подменена."""
import datetime
import os
import unittest
from unittest import mock

from chloe import holyarrs as ha
from chloe import sandbox as sb
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.content = data, status, b"x"

    def json(self):
        return self.data


class WithKey(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"HOLYARRS_KEY": "k123", "HOLYARRS_URL": "http://box:6262/"})
        p.start()
        self.addCleanup(p.stop)


class Reads(WithKey):
    def test_downloads_key_in_header_and_slim_answer(self):
        data = {"items": [{"name": "Дюна", "progress": 0.42, "poster": "https://img/x.jpg", "path": "/downloads/dune",
                           "eta_s": 600}]}
        with mock.patch("chloe.holyarrs.requests.request", return_value=Resp(data)) as req:
            out, _, failed = run_tool("holyarrs", {"action": "downloads"})
        self.assertFalse(failed)
        args, kw = req.call_args
        self.assertEqual(args, ("GET", "http://box:6262/api/v1/downloads/view"))
        self.assertEqual(kw["headers"]["X-Api-Key"], "k123")
        self.assertIn('"name":"Дюна"', out)
        self.assertIn('"progress":0.42', out)
        self.assertNotIn("img/x.jpg", out)                                   # картинки и пути модели не нужны
        self.assertNotIn("/downloads/dune", out)

    def test_calendar_range(self):
        with mock.patch("chloe.holyarrs.requests.request", return_value=Resp({"days": []})) as req:
            ha.calendar(7, today=datetime.date(2026, 11, 13))
        self.assertEqual(req.call_args[0][1], "http://box:6262/api/v1/calendar?from=2026-11-13&to=2026-11-20")

    def test_search_quotes_query(self):
        with mock.patch("chloe.holyarrs.requests.request", return_value=Resp({"results": []})) as req:
            run_tool("holyarrs", {"action": "search", "query": "космос 2014"})
        self.assertTrue(req.call_args[0][1].endswith("/api/v1/search?q=%D0%BA%D0%BE%D1%81%D0%BC%D0%BE%D1%81%202014"))

    def test_bad_key_explained(self):
        with mock.patch("chloe.holyarrs.requests.request", return_value=Resp({"error": "API key not accepted"}, 401)):
            out, _, _ = run_tool("holyarrs", {"action": "downloads"})
        self.assertIn("не принял ключ", out)

    def test_server_down_explained(self):
        import requests

        with mock.patch("chloe.holyarrs.requests.request", side_effect=requests.ConnectionError()):
            out, _, _ = run_tool("holyarrs", {"action": "calendar"})
        self.assertIn("docker compose up -d", out)


class Request(WithKey):
    def test_asks_yes_first(self):
        with mock.patch("chloe.voice.confirm", return_value=False) as ask, \
                mock.patch("chloe.holyarrs.requests.request") as req:
            out, _, _ = run_tool("holyarrs", {"action": "request", "tmdb_id": "438631", "kind": "movie", "title": "Дюна"})
        ask.assert_called_once()
        self.assertIn("«Дюна»", ask.call_args[0][0])
        req.assert_not_called()
        self.assertIn("отказался", out)

    def test_request_after_yes(self):
        with mock.patch("chloe.voice.confirm", return_value=True), \
                mock.patch("chloe.holyarrs.requests.request", return_value=Resp({"id": 5, "state": "approved"})) as req:
            out, _, _ = run_tool("holyarrs", {"action": "request", "tmdb_id": "tmdb:1399", "kind": "show", "title": "Игра престолов"})
        args, kw = req.call_args
        self.assertEqual(args, ("POST", "http://box:6262/api/v1/asks"))
        self.assertEqual(kw["json"], {"id": "tmdb:1399", "kind": "show"})
        self.assertIn("сериал «Игра престолов»", out)

    def test_bad_id_never_sent(self):
        with mock.patch("chloe.voice.confirm", return_value=True), mock.patch("chloe.holyarrs.requests.request") as req:
            out, _, _ = run_tool("holyarrs", {"action": "request", "tmdb_id": "../admin"})
        req.assert_not_called()
        self.assertIn("TMDB id цифрами", out)

    def test_risk(self):
        self.assertEqual(sb.analyse("holyarrs", {"action": "downloads"})["risk"], "low")
        self.assertEqual(sb.analyse("holyarrs", {"action": "request", "tmdb_id": "1"})["risk"], "medium")


class NoKey(unittest.TestCase):
    def test_explains_how_to_connect(self):
        with mock.patch.dict(os.environ, {"HOLYARRS_KEY": ""}), mock.patch("chloe.holyarrs.requests.request") as req:
            out, _, _ = run_tool("holyarrs", {"action": "downloads"})
        req.assert_not_called()
        self.assertIn("HOLYARRS_KEY", out)


if __name__ == "__main__":
    unittest.main()
