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
                mock.patch("chloe.holyarrs.requests.request", return_value=Resp({"asks": [], "titles": []})) as req:
            out, _, _ = run_tool("holyarrs", {"action": "request", "tmdb_id": "438631", "kind": "movie", "title": "Дюна"})
        ask.assert_called_once()
        self.assertIn("«Дюна»", ask.call_args[0][0])
        self.assertEqual({c[0][0] for c in req.call_args_list}, {"GET"})            # только проверка на дубль, запроса нет
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


class NoDuplicates(WithKey):
    def route(self, asks=(), titles=()):
        def answer(method, url, **kw):
            if "/asks" in url and method == "GET":
                return Resp({"asks": list(asks)})
            if "/library/search" in url:
                return Resp({"titles": list(titles), "albums": [], "people": []})
            raise AssertionError((method, url))
        return answer

    def test_already_asked_is_not_asked_again(self):
        asks = [{"id": 3, "kind": "movie", "tmdb_id": "438631", "ref": "tmdb:438631", "name": "Дюна", "state": "approved",
                 "state_label": "Approved"}]
        with mock.patch("chloe.voice.confirm") as ask, \
                mock.patch("chloe.holyarrs.requests.request", side_effect=self.route(asks=asks)):
            out, _, _ = run_tool("holyarrs", {"action": "request", "tmdb_id": "438631", "kind": "movie", "title": "Дюна"})
        ask.assert_not_called()
        self.assertIn("уже запрошен раньше: «Дюна» — Approved", out)

    def test_in_library_is_not_asked(self):
        titles = [{"id": 9, "name": "Интерстеллар", "kind": "movie"}]
        with mock.patch("chloe.voice.confirm") as ask, \
                mock.patch("chloe.holyarrs.requests.request", side_effect=self.route(titles=titles)) as req:
            out, _, _ = run_tool("holyarrs", {"action": "request", "tmdb_id": "157336", "kind": "movie", "title": "интерстеллар"})
        ask.assert_not_called()
        self.assertIn("уже есть в медиатеке: «Интерстеллар»", out)
        self.assertIn("/library/search?q=%D0%B8%D0%BD%D1%82%D0%B5%D1%80%D1%81%D1%82%D0%B5%D0%BB%D0%BB%D0%B0%D1%80&kind=movie",
                      req.call_args[0][1])

    def test_library_lookup(self):
        lib = {"titles": [{"id": 9, "name": "Интерстеллар", "kind": "movie", "image": "/art/1.jpg"}], "albums": [], "people": []}
        with mock.patch("chloe.holyarrs.requests.request", return_value=Resp(lib)):
            out, _, _ = run_tool("holyarrs", {"action": "library", "query": "Интерстеллар", "kind": "movie"})
        self.assertIn('"name":"Интерстеллар"', out)
        self.assertNotIn("/art/1.jpg", out)

    def test_slim_drops_media_and_empties_keeps_ids(self):
        self.assertEqual(ha.slim({"id": 1, "tmdb_id": "5", "poster": "x", "backdrop_url": "y", "seasons": [], "note": "",
                                  "year": None, "items": [{"name": "A", "thumb": "t"}] * 30}),
                         {"id": 1, "tmdb_id": "5", "items": [{"name": "A"}] * 25})


class ReadyVoice(WithKey):
    def run_watcher(self, rounds, asks_by_round, announced=None):
        """Сторож — несколько проходов подряд; возвращает сказанное."""
        said, n = [], {"i": 0}

        class Stop:
            def is_set(self):
                return n["i"] >= rounds

            def wait(self, _):
                n["i"] += 1

        def answer(method, url, **kw):
            return Resp({"asks": asks_by_round[min(n["i"], len(asks_by_round) - 1)]})
        from chloe.settings import settings

        settings.set(ha.ANNOUNCED, announced or [])
        with mock.patch("chloe.holyarrs.requests.request", side_effect=answer), \
                mock.patch("chloe.holyarrs._can_speak", return_value=True):
            ha.watcher(said.append, stop=Stop())
        return said

    def test_first_pass_is_quiet_then_tells_once(self):
        old = {"id": 1, "name": "Старое", "state": "available"}
        new = {"id": 2, "name": "Дюна", "state": "available"}
        waiting = {"id": 2, "name": "Дюна", "state": "approved"}
        said = self.run_watcher(4, [[old, waiting], [old, waiting], [old, new], [old, new]])
        self.assertEqual(said, ["Готово: «Дюна» — уже в медиатеке, можно смотреть."])   # старое не объявлено, новое — один раз

    def test_remembers_across_restarts(self):
        new = {"id": 2, "name": "Дюна", "state": "available"}
        self.assertEqual(self.run_watcher(2, [[new]], announced=["2"]), [])

    def test_waits_while_busy(self):
        new = {"id": 7, "name": "Дюна", "state": "available"}
        from chloe.settings import settings

        settings.set(ha.ANNOUNCED, ["1"])
        with mock.patch("chloe.holyarrs.requests.request", return_value=Resp({"asks": [new]})), \
                mock.patch("chloe.holyarrs._can_speak", return_value=False):
            said = []
            ha.watcher(said.append, stop=type("S", (), {"i": 0, "is_set": lambda s: s.i > 0,
                                                        "wait": lambda s, _: setattr(s, "i", 1)})())
        self.assertEqual(said, [])
        self.assertNotIn("7", settings.get(ha.ANNOUNCED))                               # не забыто — скажет позже

    def test_phrase_many(self):
        items = [{"id": i, "name": n} for i, n in enumerate(["А", "Б", "В", "Г", "Д"])]
        self.assertEqual(ha.ready_phrase(items), "Готово: «А», «Б», «В» и ещё 2 — все уже в медиатеке, можно смотреть.")


class NoKey(unittest.TestCase):
    def test_explains_how_to_connect(self):
        with mock.patch.dict(os.environ, {"HOLYARRS_KEY": ""}), mock.patch("chloe.holyarrs.requests.request") as req:
            out, _, _ = run_tool("holyarrs", {"action": "downloads"})
        req.assert_not_called()
        self.assertIn("HOLYARRS_KEY", out)


if __name__ == "__main__":
    unittest.main()
