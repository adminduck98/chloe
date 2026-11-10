"""Телефон Android через adb (Device Intelligence): экран, нажатия, приложения, ссылки. scrcpy — экран телефона в окне.

Телефон подключается кабелем (USB) или по Wi-Fi («Отладка по Wi-Fi»). Нужны «Для разработчиков» → «Отладка по USB»,
а на Xiaomi для нажатий ещё «Отладка по USB (настройки безопасности)».
"""
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

TIMEOUT = 15

# название → пакет; остальное ищем по имени пакета
APPS = {
    "telegram": "org.telegram.messenger", "телеграм": "org.telegram.messenger", "телеграмм": "org.telegram.messenger",
    "youtube": "com.google.android.youtube", "ютуб": "com.google.android.youtube",
    "whatsapp": "com.whatsapp", "ватсап": "com.whatsapp", "вотсап": "com.whatsapp",
    "instagram": "com.instagram.android", "инстаграм": "com.instagram.android",
    "chrome": "com.android.chrome", "хром": "com.android.chrome", "браузер": "com.android.chrome",
    "настройки": "com.android.settings", "settings": "com.android.settings",
    "камера": "com.android.camera", "camera": "com.android.camera",
    "галерея": "com.miui.gallery", "фото": "com.google.android.apps.photos",
    "карты": "com.google.android.apps.maps", "maps": "com.google.android.apps.maps",
    "gmail": "com.google.android.gm", "почта": "com.google.android.gm",
    "календарь": "com.google.android.calendar", "калькулятор": "com.miui.calculator",
    "часы": "com.android.deskclock", "будильник": "com.android.deskclock",
    "сообщения": "com.google.android.apps.messaging", "смс": "com.google.android.apps.messaging",
    "телефон": "com.google.android.dialer", "звонки": "com.google.android.dialer",
    "play market": "com.android.vending", "плей маркет": "com.android.vending", "google play": "com.android.vending",
    "spotify": "com.spotify.music", "спотифай": "com.spotify.music",
    "яндекс музыка": "ru.yandex.music", "tiktok": "com.zhiliaoapp.musically", "тикток": "com.zhiliaoapp.musically",
}
KEYS = {"back": 4, "назад": 4, "home": 3, "домой": 3, "recents": 187, "недавние": 187, "power": 26, "питание": 26,
        "volume_up": 24, "громче": 24, "volume_down": 25, "тише": 25, "enter": 66, "ввод": 66,
        "delete": 67, "стереть": 67, "play_pause": 85, "пауза": 85, "next": 87, "следующий": 87,
        "previous": 88, "предыдущий": 88, "wakeup": 224, "разбудить": 224}


class PhoneError(Exception):
    pass


def adb_path():
    return shutil.which("adb")


def run(args, timeout=TIMEOUT, binary=False, serial=None):
    adb = adb_path()
    if not adb:
        raise PhoneError("нет программы adb — установите: sudo apt install adb scrcpy")
    cmd = [adb] + (["-s", serial] if serial else []) + list(args)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PhoneError("телефон не ответил за {} с".format(timeout))
    out = p.stdout if binary else p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    if p.returncode != 0 or "SecurityException" in err or (not binary and "SecurityException" in out):
        text = err + ("" if binary else out)
        if "INJECT_EVENTS" in text or "WRITE_SECURE_SETTINGS" in text:
            raise PhoneError("телефон запрещает нажатия: на Xiaomi включите «Для разработчиков» → "
                             "«Отладка по USB (настройки безопасности)»")
        if "unauthorized" in text:
            raise PhoneError("телефон не разрешил отладку — подтвердите «Разрешить отладку по USB» на экране телефона")
        if "no devices" in text or "not found" in text:
            raise PhoneError("телефон не подключён")
        raise PhoneError(text.strip().splitlines()[-1] if text.strip() else "adb: ошибка {}".format(p.returncode))
    return out


def devices():
    """[(serial, state, model)] — state: device / unauthorized / offline."""
    out = run(["devices", "-l"])
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            model = next((p.split(":", 1)[1] for p in parts if p.startswith("model:")), "")
            found.append((parts[0], parts[1], model.replace("_", " ")))
    return found


def serial():
    ready = [d for d in devices() if d[1] == "device"]
    if not ready:
        if any(d[1] == "unauthorized" for d in devices()):
            raise PhoneError("телефон не разрешил отладку — подтвердите «Разрешить отладку по USB» на экране телефона")
        raise PhoneError("телефон не подключён: нужен кабель с передачей данных или «Отладка по Wi-Fi»")
    return ready[0][0]


def shell(cmd, timeout=TIMEOUT, binary=False):
    return run(["shell", cmd] if isinstance(cmd, str) else ["shell"] + list(cmd), timeout, binary, serial())


def info():
    s = serial()
    out = run(["shell", "getprop ro.product.manufacturer; getprop ro.product.model; getprop ro.build.version.release; "
                        "dumpsys battery | grep -E ' level|AC powered|USB powered'"], serial=s)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    vals = {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in lines[3:])}
    charging = vals.get("AC powered") == "true" or vals.get("USB powered") == "true"
    return {"maker": lines[0] if lines else "", "model": lines[1] if len(lines) > 1 else "",
            "android": lines[2] if len(lines) > 2 else "", "battery": vals.get("level", "?"), "charging": charging}


def screenshot():
    png = shell("screencap -p", timeout=20, binary=True)
    if not png.startswith(b"\x89PNG"):
        raise PhoneError("экран телефона не снялся (телефон заблокирован или защищённое окно)")
    return png


BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def ui_elements():
    """Видимые надписи и кнопки на экране телефона: [{text, x, y, click}] — центр элемента в пикселях телефона."""
    shell("uiautomator dump /sdcard/chloe_ui.xml", timeout=20)
    xml = shell("cat /sdcard/chloe_ui.xml", timeout=10)
    try:
        root = ET.fromstring(xml[xml.find("<"):])
    except ET.ParseError:
        raise PhoneError("не удалось прочитать экран телефона")
    items = []
    for n in root.iter("node"):
        label = (n.get("text") or n.get("content-desc") or "").strip()
        m = BOUNDS.match(n.get("bounds", ""))
        if not label or not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        items.append({"text": label, "x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "click": n.get("clickable") == "true"})
    return items


def norm(t):
    return " ".join(str(t).lower().replace("ё", "е").split())


def find_element(text):
    want = norm(text)
    items = ui_elements()
    exact = [i for i in items if norm(i["text"]) == want]
    part = [i for i in items if want and want in norm(i["text"])]
    hits = exact or part
    if not hits:
        raise PhoneError("на экране телефона нет «{}»".format(text))
    return sorted(hits, key=lambda i: not i["click"])[0]


def size():
    """Ширина и высота экрана телефона в пикселях (Override size — если пользователь менял масштаб)."""
    out = shell("wm size")
    found = dict(re.findall(r"(Physical|Override) size: (\d+x\d+)", out))
    w, h = (found.get("Override") or found.get("Physical") or "1080x2340").split("x")
    return int(w), int(h)


def tap(x, y):
    shell(["input", "tap", str(int(x)), str(int(y))])


def swipe(x1, y1, x2, y2, ms=300):
    shell(["input", "swipe"] + [str(int(v)) for v in (x1, y1, x2, y2, ms)])


def key(name):
    code = KEYS.get(norm(name).replace(" ", "_"))
    if code is None:
        raise PhoneError("не знаю клавишу «{}». Есть: {}".format(name, ", ".join(k for k in KEYS if k.isascii())))
    shell(["input", "keyevent", str(code)])


ADB_IME = "com.android.adbkeyboard/.AdbIME"   # ADBKeyBoard: печатает любой текст, в том числе по-русски


def adb_keyboard_installed():
    return "com.android.adbkeyboard" in shell("pm list packages com.android.adbkeyboard")


def _type_unicode(text):
    """Кириллица и эмодзи — через ADBKeyBoard. Клавиатура включается только на время печати, потом — прежняя."""
    import base64

    if not adb_keyboard_installed():
        raise PhoneError("печатать по-русски на телефоне нужна клавиатура ADBKeyBoard — она не установлена")
    before = shell("settings get secure default_input_method").strip()
    shell(["ime", "enable", ADB_IME])
    shell(["ime", "set", ADB_IME])
    try:
        import time
        time.sleep(0.4)   # клавиатура успевает подключиться к полю ввода
        msg = base64.b64encode(text.encode("utf-8")).decode()
        shell(["am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", msg])
        time.sleep(0.3)
    finally:
        if before and before != "null" and before != ADB_IME:
            shell(["ime", "set", before])   # клавиатура пользователя — на место


def type_text(text):
    """Латиница — встроенной командой input; всё остальное (русский, эмодзи) — через ADBKeyBoard."""
    if not text.isascii():
        return _type_unicode(text)
    for i, chunk in enumerate(text.split(" ")):
        if i:
            shell(["input", "keyevent", "62"])   # пробел
        if chunk:
            shell(["input", "text", re.sub(r"([\\\\'\"`$&|;<>()*?!~#])", r"\\\1", chunk)])


def packages():
    return [l.split(":", 1)[1].strip() for l in shell("pm list packages").splitlines() if l.startswith("package:")]


def find_app(name):
    n = norm(name)
    pkgs = packages()
    if APPS.get(n) in pkgs:
        return APPS[n]
    if n in pkgs:
        return n
    words = [w for w in re.split(r"[\s.\-_]+", n) if len(w) > 2]
    hits = [p for p in pkgs if words and all(w in p.lower() for w in words)]
    if not hits:
        raise PhoneError("на телефоне нет приложения «{}»".format(name))
    return sorted(hits, key=len)[0]


def open_app(name):
    pkg = find_app(name)
    out = shell(["monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"])
    if "No activities found" in out:
        raise PhoneError("приложение «{}» нельзя открыть".format(name))
    return pkg


def open_url(url):
    if not re.match(r"^https?://", url):
        url = "https://" + url
    shell(["am", "start", "-a", "android.intent.action.VIEW", "-d", "'{}'".format(url.replace("'", "%27"))])
    return url


MDNS = re.compile(r"(_adb-tls-(connect|pairing))\S*\s+(\d{1,3}(?:\.\d{1,3}){3}:\d+)")


def discover():
    """Телефоны, которые сами объявили себя в Wi-Fi: {"connect": [ip:port], "pairing": [ip:port]} (Android 11+, «Беспроводная отладка»)."""
    out = run(["mdns", "services"], timeout=10)
    found = {"connect": [], "pairing": []}
    for m in MDNS.finditer(out):
        key = "connect" if m.group(2) == "connect" else "pairing"
        if m.group(3) not in found[key]:
            found[key].append(m.group(3))
    return found


def connect():
    """Подключить телефон по Wi-Fi: если уже подключён — сказать; иначе найти его адрес в сети и подключиться."""
    ready = [d for d in devices() if d[1] == "device"]
    if ready:
        return "уже подключён: {}".format(ready[0][0])
    found = discover()["connect"]
    if not found:
        raise PhoneError("телефон себя в сети не объявляет: включите «Беспроводная отладка» (Для разработчиков), экран телефона "
                         "должен быть включён и телефон — в той же Wi-Fi; если он ещё не сопряжён с компьютером — «Сопряжение устройства по коду»")
    out = run(["connect", found[0]], timeout=15)
    if "connected" not in out.lower():
        raise PhoneError("не удалось подключиться к {}: {}".format(found[0], out.strip()[:100]))
    return "подключила {}".format(found[0])


def pair(code, address=None):
    """Сопряжение по коду с экрана «Сопряжение устройства по коду»: код — 6 цифр, адрес — ip:порт оттуда же (или найдётся сам)."""
    code = re.sub(r"\D", "", str(code or ""))
    if len(code) != 6:
        raise PhoneError("код сопряжения — шесть цифр с экрана телефона «Сопряжение устройства по коду»")
    address = (address or "").strip() or next(iter(discover()["pairing"]), "")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}:\d+", address):
        raise PhoneError("не вижу адрес для сопряжения: откройте на телефоне «Сопряжение устройства по коду» и держите экран включённым "
                         "(или назовите адрес с портом оттуда, например 192.168.1.6:37123)")
    out = run(["pair", address, code], timeout=20)
    if "successfully paired" not in out.lower():
        raise PhoneError("сопряжение не получилось: {}".format(out.strip()[:100]))
    return "сопряжено с {}; теперь подключаю".format(address)


def mirror():
    """Экран телефона в окне на компьютере (scrcpy): мышью и клавиатурой можно управлять телефоном."""
    exe = shutil.which("scrcpy")
    if not exe:
        raise PhoneError("нет программы scrcpy — установите: sudo apt install scrcpy")
    subprocess.Popen([exe, "-s", serial(), "--window-title", "Телефон", "--stay-awake"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
