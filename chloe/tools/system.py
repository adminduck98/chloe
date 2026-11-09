"""Программы, сайты, команды терминала и сведения о системе."""
import json
import os
import platform
import re
import shutil
import subprocess
import time
import webbrowser

from ..config import DOWNLOADS, HOME, OS_NAME
from ..voice import confirm
from .paths import P, is_executable, short
from .screen import _pyautogui


def tool_open_url(a):
    url = a["url"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return "Открыт сайт " + url


def tool_open_app(a):
    name = a["name"]
    if re.search(r'[&|<>^%"\r\n]', name):
        return "Недопустимое имя приложения: " + name
    if OS_NAME == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", name])
    elif OS_NAME == "Darwin":
        subprocess.Popen(["open", "-a", name])
    else:
        exe = shutil.which(name) or shutil.which(name.lower())
        if not exe:
            return "Приложение '" + name + "' не найдено."
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "Запускаю " + name


def tool_open_path(a):
    p = P(a["path"])
    if not p.exists():
        return "Не найдено: " + short(p)
    if is_executable(p) and not confirm("Это программа: " + p.name + ". Запустить её?"):
        return "Пользователь не разрешил запуск."
    if OS_NAME == "Windows":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif OS_NAME == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "Открыто: " + short(p)


def tool_run_command(a):
    cmd = a["command"]
    if not confirm("Выполнить команду: " + cmd + "?"):
        return "Пользователь отклонил команду."
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return "Код {}\n{}".format(res.returncode, ((res.stdout or "") + (res.stderr or ""))[:4000])
    except subprocess.TimeoutExpired:
        return "Команда не завершилась за 2 минуты."


def tool_system_info(_):
    info = {"os": OS_NAME + " " + platform.release(), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "home": str(HOME), "downloads": str(DOWNLOADS)}
    try:
        w, h = _pyautogui().size()
        info["screen"] = "{}x{}".format(w, h)
    except Exception:
        pass
    return json.dumps(info, ensure_ascii=False)
