"""Телефон как пульт: живой мозг Chloe, голос и панели — в браузере телефона, а делает всё Chloe на компьютере.

Как устроено:
- HTTPS-сервер в домашней сети (порт CHLOE_PHONE_PORT, по умолчанию 8770); сертификат свой (самоподписанный) —
  браузер один раз предупредит. HTTPS нужен, чтобы телефонный браузер дал микрофон.
- Вход по секретному коду: он в QR-коде (кнопка «Телефон» в окне Chloe) и хранится в ~/.chloe/remote/key.
  Без кода сервер отдаёт только саму страницу, без данных. Новый код: python run.py --new-phone-key.
- Телефон зовёт те же методы, что окно на компьютере (только безопасные: команда, журнал, память, файлы, город),
  а всё, что Chloe показывает в мозге, получает событиями (long-poll /api/events).
- Мозг на телефоне только показывает: сохранить или стереть мозг компьютера с телефона нельзя.
CHLOE_PHONE=off — выключить.
"""
import collections
import hmac
import http.server
import json
import os
import secrets
import socket
import socketserver
import ssl
import subprocess
import threading
import urllib.parse

from .config import DATA, UI_DIR

DIR = DATA / "remote"
PORT = int(os.environ.get("CHLOE_PHONE_PORT", "8770"))
ENABLED = os.environ.get("CHLOE_PHONE", "on") != "off"
# что телефону можно вызывать (методы класса Api в app.py)
ALLOWED = {"command", "system_status", "vision_get", "vision_set", "load_brain", "journal_list", "journal_get", "journal_delete", "journal_clear",
           "memory_list", "memory_add", "memory_edit", "memory_delete", "changes_list", "change_undo",
           "city_get", "city_set", "tts"}
QUIET = {"chloeVoice"}   # уровень микрофона компьютера телефону не нужен (шлётся десятки раз в секунду)


def key():
    DIR.mkdir(parents=True, exist_ok=True)
    f = DIR / "key"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(18))
        os.chmod(f, 0o600)
    return f.read_text().strip()


def new_key():
    (DIR / "key").unlink(missing_ok=True)
    key()


def lan_ip():
    """Адрес компьютера в домашней сети (пакет никуда не уходит — только выбор интерфейса)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def cert():
    """Самоподписанный сертификат на 10 лет (openssl)."""
    DIR.mkdir(parents=True, exist_ok=True)
    c, k = DIR / "cert.pem", DIR / "cert.key"
    if not (c.exists() and k.exists()):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(k), "-out", str(c),
                        "-days", "3650", "-subj", "/CN=Chloe"], check=True, capture_output=True, timeout=60)
        os.chmod(k, 0o600)
    return c, k


def link():
    """Ссылка для телефона: код — в части после #, она не уходит на сервер и не попадает в журналы."""
    return "https://{}:{}/#key={}".format(lan_ip(), PORT, key())


def qr_svg(text):
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return img.to_string(encoding="unicode")


class Events:
    """Очередь того, что Chloe показывает в мозге, — для телефонов."""

    def __init__(self, size=600):
        self.buf = collections.deque(maxlen=size)
        self.seq = 0
        self.cond = threading.Condition()

    def push(self, fn, args):
        if fn in QUIET:
            return
        with self.cond:
            self.seq += 1
            self.buf.append((self.seq, fn, args))
            self.cond.notify_all()

    def since(self, after, wait=20.0):
        """События после номера after. reset — телефон слишком отстал и должен перезагрузить мозг."""
        with self.cond:
            if after < 0:   # телефон только подключился: прошлое ему не нужно, мозг он загрузит целиком
                return {"next": self.seq, "reset": False, "events": []}
            if self.seq <= after:
                self.cond.wait(wait)
            first = self.buf[0][0] if self.buf else self.seq + 1
            reset = after and after + 1 < first
            return {"next": self.seq, "reset": bool(reset),
                    "events": [] if reset else [[fn, args] for n, fn, args in self.buf if n > after]}


events = Events()


def make_handler(api, secret):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(UI_DIR), **kw)

        def log_message(self, *a):
            pass

        def authed(self):
            got = self.headers.get("X-Chloe-Key", "")
            return bool(got) and hmac.compare_digest(got, secret)

        def send_json(self, data, code=200):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path in ("/", "/index.html"):
                self.send_response(302)
                self.send_header("Location", "/chloe-mind.html?app=1&remote=1")
                self.end_headers()
                return
            if url.path == "/api/events":
                if not self.authed():
                    return self.send_json({"error": "нужен код"}, 401)
                after = int(urllib.parse.parse_qs(url.query).get("after", ["0"])[0] or 0)
                return self.send_json(events.since(after))
            if url.path.startswith("/api/"):
                return self.send_json({"error": "нет такого"}, 404)
            if url.path.endswith("/") or ".." in url.path:   # без списков папок
                return self.send_json({"error": "нет такого"}, 404)
            return super().do_GET()

        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            name = url.path[len("/api/"):] if url.path.startswith("/api/") else ""
            if not self.authed():
                return self.send_json({"error": "нужен код"}, 401)
            if name == "hello":
                return self.send_json({"ok": True})
            if name == "save_brain":   # мозг на телефоне только показывает
                return self.send_json(None)
            if name not in ALLOWED:
                return self.send_json({"error": "с телефона так нельзя"}, 403)
            try:
                size = min(int(self.headers.get("Content-Length", "0")), 1 << 20)
                args = json.loads(self.rfile.read(size) or b"{}").get("args", [])
                if name == "command":   # просьба с телефона: ответ прозвучит на телефоне, а компьютер промолчит
                    return self.send_json(api.command(str(args[0]) if args else "", where="phone"))
                return self.send_json(getattr(api, name)(*args))
            except Exception as e:
                return self.send_json({"error": str(e)[:200]}, 500)

    return Handler


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # браузер телефона рвёт связь, пока не принят домашний сертификат, — это не ошибка Chloe
        import sys
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def start(api, port=PORT, use_ssl=True):
    """Запускает сервер для телефона. Возвращает сервер или None (выключено или порт занят)."""
    if not ENABLED:
        return None
    try:
        httpd = Server(("0.0.0.0", port), make_handler(api, key()))
        if use_ssl:
            c, k = cert()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(c), str(k))
            # рукопожатие — в потоке запроса, а не в общем цикле приёма: медленный телефон не держит остальных
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True, do_handshake_on_connect=False)
    except Exception as e:
        print("[телефон: не запустился — " + str(e)[:80] + "]")
        return None
    threading.Thread(target=httpd.serve_forever, daemon=True, name="phone").start()
    print("[телефон: в окне Chloe кнопка «Телефон» — QR-код для входа]")
    return httpd
