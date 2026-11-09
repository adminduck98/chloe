"""Громкость и яркость: «Хлоя, сделай погромче», «громкость на 30», «выключи звук», «убавь яркость».

Linux: звук — pactl (PulseAudio и PipeWire), яркость — через Cinnamon или GNOME (как ползунок в системе),
иначе brightnessctl. macOS: osascript. Windows: звук клавишами громкости, яркость — WMI.
"""
import re
import shutil
import subprocess

from ..config import OS_NAME

MIN_BRIGHTNESS = 5   # чтобы экран не погас совсем: в темноте пользователь не найдёт, как вернуть


def run(cmd, timeout=5):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "ошибка").strip()[:200])
    return r.stdout


def clamp(v, low=0, high=100):
    return max(low, min(high, int(round(v))))


def target(current, a, low=0):
    """Новый уровень: level — точно, change — на сколько изменить (+10 / -20)."""
    if a.get("level") is not None:
        return clamp(a["level"], low)
    if a.get("change") is not None:
        return clamp(current + int(a["change"]), low)
    return None


# ---------- звук ----------

def volume_get():
    """(громкость %, выключен ли звук)"""
    if OS_NAME == "Linux":
        vol = re.search(r"(\d+)%", run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]))
        mute = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]).split(":")[-1].strip().lower()
        return int(vol.group(1)) if vol else 0, mute in ("yes", "да")
    if OS_NAME == "Darwin":
        vol, mute = run(["osascript", "-e", "output volume of (get volume settings) & \",\" & "
                                            "output muted of (get volume settings)"]).strip().split(",")
        return int(vol), mute.strip() == "true"
    return None, None   # Windows: текущую громкость без сторонних модулей не узнать


def volume_set(level):
    if OS_NAME == "Linux":
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "{}%".format(level)])
    elif OS_NAME == "Darwin":
        run(["osascript", "-e", "set volume output volume {}".format(level)])
    else:
        import pyautogui   # клавиши громкости: 50 раз вниз до нуля, потом по 2% вверх

        pyautogui.press("volumedown", presses=50)
        pyautogui.press("volumeup", presses=level // 2)


def mute_set(on):
    if OS_NAME == "Linux":
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if on else "0"])
    elif OS_NAME == "Darwin":
        run(["osascript", "-e", "set volume {} output muted".format("with" if on else "without")])
    else:
        import pyautogui

        pyautogui.press("volumemute")


def tool_volume(a):
    level, muted = volume_get()
    if a.get("mute") is not None:
        mute_set(bool(a["mute"]))
        muted = bool(a["mute"])
    if level is None:   # Windows: уровня не знаем — точное значение или шаги клавишами
        if a.get("level") is not None:
            volume_set(clamp(a["level"]))
            return "Громкость {}%.".format(clamp(a["level"]))
        if a.get("change"):
            import pyautogui

            pyautogui.press("volumeup" if a["change"] > 0 else "volumedown", presses=abs(int(a["change"])) // 2 or 1)
            return "Сделала {}.".format("громче" if a["change"] > 0 else "тише")
        return "Звук {}.".format("выключен" if muted else "включён")
    new = target(level, a)
    if new is not None:
        volume_set(new)
        if new > 0 and muted and a.get("mute") is None:   # «сделай погромче» при выключенном звуке — включаем
            mute_set(False)
            muted = False
        level = new
    return "Громкость {}%{}.".format(level, ", звук выключен (мой голос тоже не слышен — ответ будет только текстом в окне)" if muted else "")


# ---------- яркость ----------

DBUS = {   # оболочка → (служба, путь, интерфейс)
    "cinnamon": ("org.cinnamon.SettingsDaemon.Power", "/org/cinnamon/SettingsDaemon/Power", "org.cinnamon.SettingsDaemon.Power.Screen"),
    "gnome": ("org.gnome.SettingsDaemon.Power", "/org/gnome/SettingsDaemon/Power", "org.gnome.SettingsDaemon.Power.Screen"),
}


def gdbus(dest, path, method, *args):
    return run(["gdbus", "call", "--session", "--dest", dest, "--object-path", path, "--method", method] + list(args))


def number(text):
    m = re.search(r"(\d+)", re.sub(r"\b(u?int\d+|byte|double)\b", " ", text))   # gdbus: «(uint32 55,)» — тип не число
    return int(m.group(1)) if m else None


def brightness_get():
    """(яркость %, чем управляем) или (None, причина)"""
    if OS_NAME == "Linux":
        try:
            dest, path, iface = DBUS["cinnamon"]
            return number(gdbus(dest, path, iface + ".GetPercentage")), "cinnamon"
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        try:
            dest, path, iface = DBUS["gnome"]
            return number(gdbus(dest, path, "org.freedesktop.DBus.Properties.Get", iface, "Brightness")), "gnome"
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        if shutil.which("brightnessctl"):
            cur, top = number(run(["brightnessctl", "get"])), number(run(["brightnessctl", "max"]))
            return round(cur * 100 / top), "brightnessctl"
        return None, "нет ни Cinnamon, ни GNOME, ни brightnessctl"
    if OS_NAME == "Windows":
        out = run(["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"], timeout=10)
        n = number(out)
        return (n, "wmi") if n is not None else (None, "у этого экрана яркость не меняется программно")
    return None, "на этой системе пока не умею"


def brightness_set(level, how):
    if how == "cinnamon":
        dest, path, iface = DBUS["cinnamon"]
        gdbus(dest, path, iface + ".SetPercentage", str(level))
    elif how == "gnome":
        dest, path, iface = DBUS["gnome"]
        gdbus(dest, path, "org.freedesktop.DBus.Properties.Set", iface, "Brightness", "<int32 {}>".format(level))
    elif how == "brightnessctl":
        run(["brightnessctl", "set", "{}%".format(level)])
    elif how == "wmi":
        run(["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{})".format(level)], timeout=10)


def tool_brightness(a):
    level, how = brightness_get()
    if level is None:
        return "Не могу менять яркость: " + how + "."
    new = target(level, a, low=MIN_BRIGHTNESS)
    if new is None:
        return "Яркость {}%.".format(level)
    brightness_set(new, how)
    wanted = a["level"] if a.get("level") is not None else level + int(a.get("change") or 0)
    note = " (меньше {}% не ставлю, чтобы экран не погас)".format(MIN_BRIGHTNESS) if wanted < MIN_BRIGHTNESS else ""
    return "Яркость {}%{}.".format(new, note)
