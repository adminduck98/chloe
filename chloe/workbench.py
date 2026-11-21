"""Рабочий стол в окне Chloe: терминал и файлы — для владельца, руками.

Это не инструменты модели: команду или файл выбирает сам человек в окне, поэтому голосового «да, делай» нет
(как у кнопки «удалить задачу» в «Проектах»). Но общие правила безопасности те же:
  • «запрещено» в карте прав («Команды», «Файлы: чтение», «Файлы: изменение») выключает и эти окна;
  • в Private Vault окно не заходит и внутри ничего не показывает;
  • домашнюю папку, Рабочий стол, Документы и Загрузки удалить нельзя; удаление — только в корзину;
  • каждое изменение файлов — в «Изменения файлов» (его можно отменить), команды — в журнал;
  • команда, запускающая вторую Chloe, не выполняется; ключи API в терминал не передаются.
С телефона эти методы недоступны (их нет в remote.ALLOWED).
"""
import os
import re
import shlex
import signal
import subprocess
import threading
import time

from .config import DESKTOP, DOCUMENTS, DOWNLOADS, HOME, OS_NAME
from .tools.paths import P, PROTECTED
from .tools.paths import short as _short


def short(p):
    s = _short(p)
    return "~" if s in ("~/.", "~/") else s

MAX_OUT = 200_000          # сколько вывода держим на одну команду (хвост)
MAX_ITEMS = 500            # сколько строк папки отдаём окну
KEEP_DONE = 20             # сколько завершённых команд помнить
SECRET_ENV = re.compile(r"API_KEY|TOKEN|SECRET|PASSWORD", re.I)
CD = re.compile(r"^\s*cd(?:\s+(.*?))?\s*$")


def _blocked(key):
    from .permissions import CATEGORIES, permissions

    if permissions.level(key) == "block":
        return "«{}» запрещено в карте прав (кнопка «Доступ»)".format(CATEGORIES[key][0])
    return None


def _private(p):
    from .permissions import permissions

    return permissions.in_vault(str(p))


def _clean_env():
    """Окружение для команд владельца — без ключей, которые Chloe прочитала из keys.env."""
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
    env.setdefault("TERM", "dumb")
    env["PAGER"] = "cat"                 # git log и man не ждут нажатия клавиш
    env["GIT_PAGER"] = "cat"
    return env


# ---------------------------------------------------------------- терминал
class Terminal:
    def __init__(self):
        self.cwd = HOME
        self.jobs = {}
        self.lock = threading.Lock()
        self.seq = 0

    def state(self):
        running = [j["id"] for j in self.jobs.values() if j["code"] is None]
        return {"cwd": str(self.cwd), "short": short(self.cwd), "running": running}

    def start(self, cmd):
        cmd = str(cmd or "").strip()
        if not cmd:
            return {"error": "пустая команда", **self.state()}
        why = _blocked("commands")
        if why:
            return {"error": why, **self.state()}
        m = CD.match(cmd)
        if m:
            return self._cd(m.group(1))
        from .tools.system import starts_chloe

        if starts_chloe(cmd):
            return {"error": "это запуск самой Chloe — получилась бы вторая. Я уже работаю.", **self.state()}
        if _private(self.cwd):
            return {"error": "эта папка приватная (Private Vault)", **self.state()}
        kw = {}
        if OS_NAME == "Windows":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kw["start_new_session"] = True     # «Стоп» останавливает команду со всеми её детьми
        try:
            proc = subprocess.Popen(cmd, shell=True, cwd=str(self.cwd), env=_clean_env(), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1, **kw)
        except OSError as e:
            return {"error": str(e), **self.state()}
        with self.lock:
            self.seq += 1
            job = {"id": self.seq, "cmd": cmd, "cwd": str(self.cwd), "out": "", "cut": 0, "code": None,
                   "proc": proc, "started": time.time()}
            self.jobs[job["id"]] = job
            self._forget_old()
        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        return {"id": job["id"], **self.state()}

    def _cd(self, arg):
        target = self.cwd
        if arg:
            try:
                parts = shlex.split(arg)
            except ValueError:
                parts = [arg]
            raw = parts[0] if parts else "~"
            if raw == "-":
                raw = "~"
            path = P(raw) if raw.startswith(("~", "$")) or os.path.isabs(raw) else self.cwd / raw
            target = path
        else:
            target = HOME
        try:
            target = target.resolve()
        except OSError:
            pass
        if not target.is_dir():
            return {"error": "нет такой папки: " + short(target), **self.state()}
        if _private(target):
            return {"error": "эта папка приватная (Private Vault)", **self.state()}
        self.cwd = target
        return {"cd": True, **self.state()}

    def cd(self, path):
        return self._cd(shlex.quote(str(path)))

    def _pump(self, job):
        proc = job["proc"]
        for line in proc.stdout:
            with self.lock:
                job["out"] += line
                if len(job["out"]) > MAX_OUT:          # держим хвост: в окне всё равно видно последнее
                    drop = len(job["out"]) - MAX_OUT
                    job["out"] = job["out"][drop:]
                    job["cut"] += drop
        proc.stdout.close()
        proc.wait()
        with self.lock:
            job["code"] = proc.returncode
            job["ended"] = time.time()
        try:
            from .journal import journal

            journal.add("tool", "Терминал", "Вы выполнили: " + job["cmd"],
                        {"command": job["cmd"], "cwd": job["cwd"], "code": job["code"], "by": "окно"}, ok=job["code"] == 0)
        except Exception:
            pass

    def poll(self, jid, offset=0):
        """Новый вывод команды с позиции offset (позиция считается от начала, даже если голову уже отрезали)."""
        job = self.jobs.get(int(jid))
        if not job:
            return {"error": "нет такой команды", "done": True}
        with self.lock:
            start = max(0, int(offset or 0) - job["cut"])
            text = job["out"][start:]
            end = job["cut"] + len(job["out"])
            return {"out": text, "offset": end, "done": job["code"] is not None, "code": job["code"],
                    "skipped": int(offset or 0) < job["cut"]}

    def stop(self, jid):
        job = self.jobs.get(int(jid))
        if not job or job["code"] is not None:
            return False
        proc = job["proc"]
        try:
            if OS_NAME == "Windows":
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        threading.Timer(2.0, lambda: proc.poll() is None and proc.kill()).start()
        return True

    def _forget_old(self):
        done = sorted((j for j in self.jobs.values() if j["code"] is not None), key=lambda j: j["id"])
        for j in done[:-KEEP_DONE]:
            self.jobs.pop(j["id"], None)


terminal = Terminal()


# ---------------------------------------------------------------- файлы
def places():
    out = []
    for name, p in (("Дом", HOME), ("Рабочий стол", DESKTOP), ("Документы", DOCUMENTS), ("Загрузки", DOWNLOADS)):
        if p.is_dir():
            out.append({"name": name, "path": str(p)})
    return out


def list_dir(path="", hidden=False):
    why = _blocked("files_read")
    if why:
        return {"error": why}
    p = P(path or "~")
    try:
        p = p.resolve()
    except OSError:
        pass
    if not p.is_dir():
        return {"error": "это не папка: " + short(p)}
    if _private(p):
        return {"error": "эта папка приватная (Private Vault)", "path": str(p), "short": short(p),
                "parent": str(p.parent)}
    items = []
    try:
        entries = list(os.scandir(p))
    except OSError as e:
        return {"error": "не открыть: " + (e.strerror or str(e)), "path": str(p), "short": short(p), "parent": str(p.parent)}
    for e in entries:
        if not hidden and e.name.startswith("."):
            continue
        try:
            is_dir = e.is_dir()
            st = e.stat()
            size, mtime = (0 if is_dir else st.st_size), st.st_mtime
        except OSError:
            is_dir, size, mtime = False, 0, 0
        items.append({"name": e.name, "path": os.path.join(str(p), e.name), "dir": is_dir, "size": size,
                      "mtime": mtime, "private": is_dir and _private(os.path.join(str(p), e.name))})
    items.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    total = len(items)
    return {"path": str(p), "short": short(p), "parent": str(p.parent) if p.parent != p else "",
            "items": items[:MAX_ITEMS], "total": total, "places": places()}


def _change_check(p):
    why = _blocked("files_change")
    if why:
        return why
    if _private(p) or _private(p.parent):
        return "это приватная папка (Private Vault)"
    return None


def _valid_name(name):
    name = str(name or "").strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
        return None
    return name


def make_dir(folder, name):
    from .changes import changes

    name = _valid_name(name)
    if not name:
        return {"error": "неподходящее имя"}
    p = P(folder) / name
    why = _change_check(p)
    if why:
        return {"error": why}
    if p.exists():
        return {"error": "уже есть: " + name}
    p.mkdir(parents=False)
    changes.record("create_folder", dst=p)
    return {"ok": True, "path": str(p)}


def rename(path, new_name):
    from .changes import changes

    src = P(path)
    name = _valid_name(new_name)
    if not name:
        return {"error": "неподходящее имя"}
    if not src.exists():
        return {"error": "не найдено: " + short(src)}
    why = _change_check(src)
    if why:
        return {"error": why}
    if src.resolve() in PROTECTED:
        return {"error": "эту папку переименовывать нельзя"}
    dst = src.with_name(name)
    if dst.exists():
        return {"error": "такое имя уже есть"}
    src.rename(dst)
    changes.record("move", src=src, dst=dst)
    return {"ok": True, "path": str(dst)}


def trash(path):
    """В корзину (не насовсем). Окно спрашивает «Точно?» вторым нажатием — это и есть согласие."""
    from .changes import changes

    p = P(path)
    if not p.exists():
        return {"error": "не найдено: " + short(p)}
    why = _change_check(p)
    if why:
        return {"error": why}
    if p.resolve() in PROTECTED or len(p.resolve().parts) <= 2:
        return {"error": "это важная папка — её удалить нельзя"}
    try:
        from send2trash import send2trash
    except ImportError:
        return {"error": "не могу удалить безопасно: нет пакета send2trash (pip install send2trash)"}
    send2trash(str(p))
    changes.record("delete", src=p.resolve())
    return {"ok": True}


def open_path(path):
    why = _blocked("files_read")
    if why:
        return {"error": why}
    p = P(path)
    if _private(p):
        return {"error": "это приватная папка (Private Vault)"}
    from .tools.system import tool_open_path

    return {"message": tool_open_path({"path": str(p)})}
