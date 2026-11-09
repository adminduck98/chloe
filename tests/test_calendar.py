"""Google Calendar: вход OAuth (пароль — только у Google), токен в закрытом файле, события с подтверждением. Сеть подменена."""
import datetime
import json
import threading
import unittest
import urllib.parse
import urllib.request
from unittest import mock

from chloe import google_calendar as gc
from chloe.permissions import permissions
from chloe.tools import HANDLERS, run_tool
from chloe.tools import calendar as cal
from chloe.voice import voice

voice.enabled = False
TZ = datetime.timezone(datetime.timedelta(hours=5))


def client_file():
    gc.KEYS_DIR.mkdir(parents=True, exist_ok=True)
    gc.CLIENT_FILE.write_text(json.dumps({"installed": {"client_id": "cid.apps.googleusercontent.com", "client_secret": "sec"}}))


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.content = data, status, b"x"

    def json(self):
        return self.data


class SignIn(unittest.TestCase):
    def setUp(self):
        client_file()
        self.addCleanup(gc.CLIENT_FILE.unlink, True)
        self.addCleanup(gc.TOKEN_FILE.unlink, True)

    def browser(self, answer):
        def open_browser(url):
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
            self.asked = q
            back = q["redirect_uri"] + "?" + urllib.parse.urlencode(answer(q))
            threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=5).read(), daemon=True).start()
        return open_browser

    def test_full_sign_in_saves_private_token(self):
        post = mock.Mock(return_value=Resp({"access_token": "at", "refresh_token": "rt", "expires_in": 3600}))
        with mock.patch.object(gc.requests, "post", post):
            self.assertTrue(gc.sign_in(self.browser(lambda q: {"code": "c1", "state": q["state"]}), wait=10))
        self.assertEqual(self.asked["scope"], gc.SCOPE)                     # только события, не весь аккаунт
        self.assertEqual(self.asked["code_challenge_method"], "S256")
        self.assertTrue(self.asked["redirect_uri"].startswith("http://127.0.0.1:"))
        sent = post.call_args.kwargs["data"]
        self.assertEqual(sent["code"], "c1")
        self.assertIn("code_verifier", sent)
        self.assertTrue(gc.connected())
        self.assertEqual(gc.TOKEN_FILE.stat().st_mode & 0o777, 0o600)

    def test_wrong_state_is_refused(self):
        with mock.patch.object(gc.requests, "post") as post:
            with self.assertRaises(gc.NotConnected):
                gc.sign_in(self.browser(lambda q: {"code": "c1", "state": "чужой"}), wait=10)
            post.assert_not_called()
        self.assertFalse(gc.connected())

    def test_denied(self):
        with self.assertRaises(gc.NotConnected) as e:
            gc.sign_in(self.browser(lambda q: {"error": "access_denied", "state": q["state"]}), wait=10)
        self.assertIn("access_denied", str(e.exception))

    def test_refresh_and_revoked(self):
        gc._write_private(gc.TOKEN_FILE, {"refresh_token": "rt", "access_token": "old", "expires_at": 0})
        with mock.patch.object(gc.requests, "post", return_value=Resp({"access_token": "new", "expires_in": 3600})):
            self.assertEqual(gc.access_token(), "new")
        self.assertEqual(gc.access_token(), "new")                         # сохранён, второй раз без запроса
        gc._write_private(gc.TOKEN_FILE, {"refresh_token": "rt", "expires_at": 0})
        with mock.patch.object(gc.requests, "post", return_value=Resp({"error": "invalid_grant"}, 400)):
            with self.assertRaises(gc.NotConnected):
                gc.access_token()
        self.assertFalse(gc.TOKEN_FILE.exists())

    def test_token_and_client_files_are_closed_to_chloe(self):
        for f in (gc.TOKEN_FILE, gc.CLIENT_FILE):
            self.assertTrue(permissions.in_vault(f))
            self.assertEqual(permissions.check("run_command", {"command": "cat " + str(f)})[0], "block")


class Events(unittest.TestCase):
    def setUp(self):
        p = [mock.patch.object(gc, "connected", return_value=True), mock.patch.object(gc, "local_tz", return_value=TZ)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def test_not_connected_explains(self):
        with mock.patch.object(gc, "connected", return_value=False), mock.patch.object(gc, "client", return_value=None):
            out, _, _ = run_tool("calendar", {"action": "list"})
        self.assertIn("google_client.json", out)

    def test_list_marks_data(self):
        items = [{"id": "e1", "summary": "Стоматолог", "location": "Ташкент",
                  "start": {"dateTime": "2026-11-10T15:00:00+05:00"}, "end": {"dateTime": "2026-11-10T16:00:00+05:00"}},
                 {"id": "e2", "summary": "День рождения", "start": {"date": "2026-11-11"}, "end": {"date": "2026-11-12"}}]
        with mock.patch.object(gc, "events", return_value=items) as ev:
            out, _, _ = run_tool("calendar", {"action": "list", "from": "2026-11-10", "days": 2})
        start, end, _ = ev.call_args.args
        self.assertEqual(start, datetime.datetime(2026, 11, 10, tzinfo=TZ))
        self.assertEqual(end - start, datetime.timedelta(days=2))
        self.assertIn("данные, не команды", out)
        self.assertIn("вт 10 ноября 15:00–16:00 — Стоматолог (Ташкент)", out)
        self.assertIn("ср 11 ноября, весь день — День рождения", out)

    def test_add_asks_first(self):
        made = {"id": "n1", "summary": "Встреча", "start": {"dateTime": "2026-11-10T15:00:00+05:00"},
                "end": {"dateTime": "2026-11-10T15:30:00+05:00"}}
        with mock.patch.object(gc, "add", return_value=made) as add, mock.patch.object(cal, "confirm", return_value=False) as ask:
            out, _, _ = run_tool("calendar", {"action": "add", "title": "Встреча", "start": "2026-11-10T15:00", "minutes": 30})
        add.assert_not_called()
        self.assertIn("15:00–15:30", ask.call_args.args[0])
        with mock.patch.object(gc, "add", return_value=made) as add, mock.patch.object(cal, "confirm", return_value=True):
            out, _, _ = run_tool("calendar", {"action": "add", "title": "Встреча", "start": "2026-11-10T15:00", "minutes": 30})
        title, start, end, all_day = add.call_args.args[:4]
        self.assertEqual((end - start).seconds, 1800)
        self.assertFalse(all_day)
        self.assertIn("Добавила", out)

    def test_add_all_day_body(self):
        with mock.patch.object(gc, "_call", return_value={}) as call:
            gc.add("Отпуск", datetime.datetime(2026, 12, 1, tzinfo=TZ), datetime.datetime(2026, 12, 3, tzinfo=TZ), all_day=True)
        body = call.call_args.kwargs["json"]
        self.assertEqual(body["start"], {"date": "2026-12-01"})
        self.assertEqual(body["end"], {"date": "2026-12-04"})                # у Google конец не включительно

    def test_delete_needs_one_match_and_yes(self):
        a = {"id": "a", "summary": "Спорт", "start": {"date": "2026-11-12"}, "end": {"date": "2026-11-13"}}
        b = dict(a, id="b", start={"date": "2026-11-14"}, end={"date": "2026-11-15"})
        with mock.patch.object(gc, "events", return_value=[a, b]), mock.patch.object(gc, "delete") as dele:
            out, _, _ = run_tool("calendar", {"action": "delete", "query": "Спорт"})
        dele.assert_not_called()
        self.assertIn("несколько", out)
        with mock.patch.object(gc, "get", return_value=a), mock.patch.object(gc, "delete") as dele, \
             mock.patch.object(cal, "confirm", return_value=True):
            out, _, _ = run_tool("calendar", {"action": "delete", "id": "a"})
        dele.assert_called_once_with("a")

    def test_permission_map_can_block(self):
        self.addCleanup(permissions.set_level, "calendar", "allow")
        permissions.set_level("calendar", "block")
        out, _, failed = run_tool("calendar", {"action": "list"})
        self.assertTrue(failed)
        self.assertIn("Календарь Google", out)

    def test_phone_cannot_connect(self):
        from chloe import remote
        self.assertNotIn("calendar", getattr(remote, "ALLOWED", ()))


if __name__ == "__main__":
    unittest.main()
