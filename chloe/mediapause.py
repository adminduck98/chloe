"""Пауза музыки и видео перед важным сообщением (правило владельца, 16.11.2026: «если играет музыка или видео,
а есть важная новость — поставь на паузу, потом скажи»).

Плееры Linux (Firefox с YouTube, VLC, Spotify и др.) видны через D-Bus MPRIS: org.mpris.MediaPlayer2.*.
Chloe ставит на паузу только то, что сейчас играет, и после сообщения включает именно это — то, что владелец сам
поставил на паузу, не трогает. Без gdbus или без плееров — ничего не делает.
"""
import re
import shutil
import subprocess

PATH = "/org/mpris/MediaPlayer2"
IFACE = "org.mpris.MediaPlayer2.Player"


def _gdbus(*args):
    try:
        r = subprocess.run(["gdbus", "call", "--session"] + list(args), capture_output=True, text=True, timeout=3)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def players():
    if not shutil.which("gdbus"):
        return []
    out = _gdbus("--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                 "--method", "org.freedesktop.DBus.ListNames")
    return re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", out)


def playing(name):
    out = _gdbus("--dest", name, "--object-path", PATH, "--method", "org.freedesktop.DBus.Properties.Get",
                 IFACE, "PlaybackStatus")
    return "Playing" in out


def pause_all():
    """Поставить на паузу всё, что играет. Возвращает, что поставлено (для resume)."""
    paused = []
    for name in players():
        if playing(name):
            _gdbus("--dest", name, "--object-path", PATH, "--method", IFACE + ".Pause")
            paused.append(name)
    return paused


def resume(paused):
    for name in paused or []:
        _gdbus("--dest", name, "--object-path", PATH, "--method", IFACE + ".Play")


def announce(say, text):
    """Важное сообщение: пауза — сказать — продолжить."""
    paused = pause_all()
    try:
        say(text)
    finally:
        resume(paused)
