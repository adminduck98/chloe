"""Телефон-пульт: вход только по коду, безопасные методы, события мозга, HTTPS. Всё во временной домашней папке."""
import json
import os
import ssl
import threading
import time
import unittest
import urllib.error
import urllib.request

from chloe import remote
from chloe.app import Api
from chloe.brain import brain
from chloe.config import BRAIN_FILE
from chloe.signals import commands, drain
from chloe.voice import voice

voice.enabled = False


def request(base, path, key=None, body=None, ctx=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Chloe-Key": key} if key else {}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class Phone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = remote.start(Api(), port=0, use_ssl=False)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.key = remote.key()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, name, *args, key="ok"):
        code, text = request(self.base, "/api/" + name, self.key if key == "ok" else key, {"args": list(args)})
        return code, json.loads(text) if text else None

    def test_page_is_open_data_is_not(self):
        code, text = request(self.base, "/chloe-mind.html")
        self.assertEqual(code, 200)
        self.assertIn("remote.js", text)
        self.assertEqual(self.call("journal_list", key=None)[0], 401)
        self.assertEqual(self.call("journal_list", key="wrong-key-123")[0], 401)
        self.assertEqual(request(self.base, "/api/events?after=0")[0], 401)

    def test_command_goes_to_chloe(self):
        drain(commands)
        self.assertEqual(self.call("command", "какая погода")[0], 200)
        self.assertEqual(commands.get(timeout=2), "какая погода")

    def test_panels_work(self):
        code, items = self.call("journal_list", "", "", 5, 0)
        self.assertEqual(code, 200)
        self.assertIsInstance(items, list)
        self.assertEqual(self.call("memory_list")[0], 200)

    def test_phone_cannot_touch_the_brain_or_open_things(self):
        BRAIN_FILE.write_text('{"keep": true}')
        self.assertEqual(self.call("save_brain", "")[0], 200)
        self.assertEqual(BRAIN_FILE.read_text(), '{"keep": true}')   # стереть мозг с телефона нельзя
        for name in ("open_folder", "phone_link", "install_voice", "__init__"):
            self.assertEqual(self.call(name, "/")[0], 403, name)

    def test_events_reach_the_phone(self):
        start = json.loads(request(self.base, "/api/events?after=-1", self.key)[1])
        self.assertEqual(start["events"], [])   # прошлое при подключении не нужно
        threading.Timer(0.3, lambda: brain.js("chloeReply", "Готово")).start()
        t0 = time.time()
        got = json.loads(request(self.base, "/api/events?after=%d" % start["next"], self.key)[1])
        self.assertLess(time.time() - t0, 5)   # long-poll отдал сразу, как появилось
        self.assertIn(["chloeReply", ["Готово"]], got["events"])

    def test_mic_level_is_not_sent(self):
        start = remote.events.seq
        brain.js("chloeVoice", 0.5, "user")
        self.assertEqual(remote.events.seq, start)

    def test_link_and_key_are_private(self):
        self.assertIn("#key=" + self.key, remote.link())
        self.assertEqual(oct(os.stat(remote.DIR / "key").st_mode & 0o777), "0o600")
        self.assertIn("<svg", remote.qr_svg(remote.link()))

    def test_allowed_methods_exist(self):
        for name in remote.ALLOWED:
            self.assertTrue(callable(getattr(Api, name, None)), name)


class Https(unittest.TestCase):
    def test_https_with_own_certificate(self):
        httpd = remote.start(Api(), port=0, use_ssl=True)
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # свой сертификат: телефон один раз соглашается
            code, text = request("https://127.0.0.1:%d" % httpd.server_address[1], "/api/hello", remote.key(), {}, ctx)
            self.assertEqual((code, json.loads(text)), (200, {"ok": True}))
            self.assertEqual(oct(os.stat(remote.DIR / "cert.key").st_mode & 0o777), "0o600")
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
