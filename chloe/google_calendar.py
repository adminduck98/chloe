"""Google Calendar — первый внешний сервис (коннектор) Chloe.

Вход — OAuth Google для программ на компьютере: пользователь сам входит в аккаунт в браузере и сам разрешает
доступ. Пароль Chloe не видит. Нужен свой «OAuth client» (тип Desktop app) из Google Cloud Console — файл
~/.config/chloe/google_client.json. После входа токен лежит в ~/.config/chloe/google_token.json (права 600).
Оба файла закрыты для инструментов Chloe (как и keys.env). Доступ — только к событиям календаря (calendar.events).
Отключить: «Хлоя, отключи календарь» — токен отзывается и удаляется.
"""
import base64
import datetime
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser

import requests

from .config import KEYS_DIR

CLIENT_FILE = KEYS_DIR / "google_client.json"
TOKEN_FILE = KEYS_DIR / "google_token.json"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SIGN_IN_WAIT = 300   # сколько секунд ждать, пока пользователь войдёт в браузере


class NotConnected(Exception):
    pass


def _write_private(path, data):
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(KEYS_DIR, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def client():
    """client_id и client_secret из скачанного файла (ключ installed или web)."""
    try:
        data = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    c = data.get("installed") or data.get("web") or data
    return c if c.get("client_id") and c.get("client_secret") else None


def connected(token_file=None):
    try:
        return bool(json.loads((token_file or TOKEN_FILE).read_text(encoding="utf-8")).get("refresh_token"))
    except (OSError, ValueError):
        return False


# --- вход ---
class _Catch(http.server.BaseHTTPRequestHandler):
    result = None

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" not in q and "error" not in q:
            self.send_response(404)
            self.end_headers()
            return
        type(self).result = {k: v[0] for k, v in q.items()}
        ok = "code" in q
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(("<h2>{}</h2><p>Окно можно закрыть.</p>".format(
            "Готово: Chloe подключена к Google Calendar." if ok else "Доступ не дан.")).encode("utf-8"))

    def log_message(self, *a):
        pass


def sign_in(open_browser=webbrowser.open, wait=SIGN_IN_WAIT, scope=None, token_file=None):
    """Открывает страницу входа Google; пользователь входит и разрешает сам. Ждёт ответа на 127.0.0.1.
    scope и token_file — для других сервисов Google на том же клиенте (YouTube); по умолчанию — календарь."""
    c = client()
    if not c:
        raise NotConnected("нет файла {} — сначала создайте OAuth client (Desktop app) в Google Cloud Console".format(CLIENT_FILE))
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    class Handler(_Catch):
        result = None

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    redirect = "http://127.0.0.1:{}/".format(server.server_address[1])
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": scope or SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    server.timeout = 1
    try:
        open_browser(url)
        end = time.time() + wait
        while Handler.result is None and time.time() < end:
            server.handle_request()
    finally:
        server.server_close()
    r = Handler.result
    if not r:
        raise NotConnected("вход не завершён за {} минут".format(wait // 60))
    if r.get("state") != state:
        raise NotConnected("ответ Google не совпал с запросом — вход отменён")
    if "code" not in r:
        raise NotConnected("Google: доступ не дан ({})".format(r.get("error", "отказ")))
    resp = requests.post(TOKEN_URL, data={
        "code": r["code"], "client_id": c["client_id"], "client_secret": c["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier}, timeout=20)
    tok = resp.json()
    if resp.status_code != 200 or "refresh_token" not in tok:
        raise NotConnected("Google не выдал доступ: {}".format(tok.get("error_description") or tok.get("error") or resp.status_code))
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    _write_private(token_file or TOKEN_FILE, tok)
    return True


def sign_out(token_file=None):
    """Отозвать доступ у Google и удалить токен."""
    token_file = token_file or TOKEN_FILE
    try:
        tok = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    try:
        requests.post(REVOKE_URL, data={"token": tok.get("refresh_token") or tok.get("access_token")}, timeout=10)
    except requests.RequestException:
        pass
    token_file.unlink(missing_ok=True)
    return True


_lock = threading.Lock()


def access_token(token_file=None, what="календарь"):
    token_file = token_file or TOKEN_FILE
    with _lock:
        try:
            tok = json.loads(token_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise NotConnected("{} не подключён".format(what))
        if tok.get("access_token") and tok.get("expires_at", 0) > time.time():
            return tok["access_token"]
        c = client()
        if not c or not tok.get("refresh_token"):
            raise NotConnected("{} не подключён".format(what))
        resp = requests.post(TOKEN_URL, data={"client_id": c["client_id"], "client_secret": c["client_secret"],
                                              "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}, timeout=20)
        new = resp.json()
        if resp.status_code != 200 or "access_token" not in new:
            if new.get("error") == "invalid_grant":   # доступ отозван в аккаунте Google
                token_file.unlink(missing_ok=True)
                raise NotConnected("Google отозвал доступ — подключите {} заново".format(what))
            raise NotConnected("Google не обновил доступ: {}".format(new.get("error") or resp.status_code))
        tok.update(access_token=new["access_token"], expires_at=time.time() + int(new.get("expires_in", 3600)) - 60)
        _write_private(token_file, tok)
        return tok["access_token"]


def _call(method, url, **kw):
    resp = requests.request(method, url, headers={"Authorization": "Bearer " + access_token()}, timeout=20, **kw)
    if resp.status_code == 401:
        raise NotConnected("Google не принял доступ — подключите календарь заново")
    if resp.status_code >= 400:
        try:
            msg = resp.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            msg = str(resp.status_code)
        raise RuntimeError("Google Calendar: " + msg)
    return resp.json() if resp.content else {}


# --- события ---
def local_tz():
    return datetime.datetime.now().astimezone().tzinfo


def events(start, end, query=None, limit=25):
    params = {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
              "orderBy": "startTime", "maxResults": limit}
    if query:
        params["q"] = query
    return _call("GET", API, params=params).get("items", [])


def add(title, start, end=None, all_day=False, location=None, description=None):
    body = {"summary": title}
    if all_day:
        day = start.date()
        last = (end.date() if end else day) + datetime.timedelta(days=1)   # у Google конец дня — не включительно
        body["start"], body["end"] = {"date": day.isoformat()}, {"date": last.isoformat()}
    else:
        body["start"] = {"dateTime": start.isoformat()}
        body["end"] = {"dateTime": (end or start + datetime.timedelta(hours=1)).isoformat()}
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    return _call("POST", API, json=body)


def get(event_id):
    return _call("GET", API + "/" + urllib.parse.quote(event_id, safe=""))


def delete(event_id):
    _call("DELETE", API + "/" + urllib.parse.quote(event_id, safe=""))
    return True
