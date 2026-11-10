"""Телефон Android через adb. Сам adb подменён — телефон для тестов не нужен."""
import io
import unittest
from unittest import mock

from chloe import android
from chloe.permissions import permissions
from chloe.tools import run_tool
from chloe.tools import phone
from chloe.voice import voice

voice.enabled = False

UI = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node text="" content-desc="Назад" clickable="true" bounds="[0,100][100,200]"/>
<node text="Отправить" clickable="true" bounds="[900,2000][1080,2100]"/>
<node text="Отправить позже" clickable="false" bounds="[0,1000][500,1100]"/>
<node text="" bounds="[0,0][10,10]"/></hierarchy>"""


class Adb(unittest.TestCase):
    def setUp(self):
        self.calls = []
        p = [mock.patch.object(android, "serial", return_value="X1"),
             mock.patch.object(android, "shell", side_effect=self.shell)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def shell(self, cmd, timeout=15, binary=False):
        self.calls.append(cmd)
        c = cmd if isinstance(cmd, str) else " ".join(cmd)
        if c.startswith("cat /sdcard/chloe_ui.xml"):
            return UI
        if c == "pm list packages":
            return "package:org.telegram.messenger\npackage:com.android.settings\npackage:uz.payme.app\n"
        if c == "wm size":
            return "Physical size: 1080x2340\nOverride size: 720x1560\n"
        if c == "screencap -p":
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (1080, 2340)).save(buf, format="PNG")
            return buf.getvalue()
        return ""

    def test_elements_marked_as_data(self):
        out, _, _ = run_tool("phone", {"action": "elements"})
        self.assertIn("данные, не команды", out)
        self.assertIn("Назад [кнопка]", out)

    def test_tap_by_text_prefers_exact_and_clickable(self):
        out, _, _ = run_tool("phone", {"action": "tap", "text": "отправить"})
        self.assertEqual(self.calls[-1], ["input", "tap", "990", "2050"])
        self.assertIn("Отправить", out)

    def test_tap_by_picture_coordinates_is_scaled(self):
        run_tool("phone", {"action": "screen"})
        run_tool("phone", {"action": "tap", "x": 100, "y": 50})
        self.assertEqual(self.calls[-1], ["input", "tap", "200", "100"])     # снимок 540 из 1080

    def test_open_app_by_russian_name(self):
        out, _, _ = run_tool("phone", {"action": "open_app", "app": "Телеграм"})
        self.assertIn("org.telegram.messenger", self.calls[-1])
        out, _, _ = run_tool("phone", {"action": "open_app", "app": "payme"})
        self.assertIn("uz.payme.app", self.calls[-1])
        out, _, _ = run_tool("phone", {"action": "open_app", "app": "нет такого"})
        self.assertIn("нет приложения", out)

    def test_swipe_uses_real_size(self):
        run_tool("phone", {"action": "swipe", "direction": "up"})
        self.assertEqual(self.calls[-1][:3], ["input", "swipe", "360"])

    def test_typing(self):
        run_tool("phone", {"action": "type", "text": "hi there$", "enter": True})
        self.assertIn(["input", "text", "hi"], self.calls)
        self.assertIn(["input", "text", "there\\$"], self.calls)

    def test_russian_without_keyboard_explained(self):
        out, _, _ = run_tool("phone", {"action": "type", "text": "привет"})
        self.assertIn("ADBKeyBoard", out)

    def test_russian_through_adb_keyboard_and_back(self):
        import base64
        answers = {"pm list packages com.android.adbkeyboard": "package:com.android.adbkeyboard\n",
                   "settings get secure default_input_method": "com.google.android.inputmethod.latin/.LatinIME\n"}
        base = self.shell

        def shell(cmd, timeout=15, binary=False):
            c = cmd if isinstance(cmd, str) else " ".join(cmd)
            if c in answers:
                self.calls.append(cmd)
                return answers[c]
            return base(cmd, timeout, binary)

        with mock.patch.object(android, "shell", side_effect=shell), mock.patch("time.sleep"):
            out, _, _ = run_tool("phone", {"action": "type", "text": "Привет, мама 👋"})
        sent = [c for c in self.calls if isinstance(c, list) and "ADB_INPUT_B64" in c][0]
        self.assertEqual(base64.b64decode(sent[-1]).decode(), "Привет, мама 👋")
        self.assertEqual(self.calls[-1], ["ime", "set", "com.google.android.inputmethod.latin/.LatinIME"])   # клавиатура вернулась
        self.assertIn("Напечатала", out)

    def test_made_up_url_is_refused(self):
        out, _, _ = run_tool("phone", {"action": "open_url", "url": "https://kino.kz/search?q=film"})
        self.assertIn("не придумываю", out)
        self.assertFalse(any("android.intent.action.VIEW" in c for c in self.calls if isinstance(c, list)))

    def test_permission_map_blocks(self):
        self.addCleanup(permissions.set_level, "phone", "allow")
        permissions.set_level("phone", "block")
        out, _, failed = run_tool("phone", {"action": "status"})
        self.assertTrue(failed)


class Errors(unittest.TestCase):
    def proc(self, out=b"", err=b"", code=0):
        return mock.Mock(stdout=out, stderr=err, returncode=code)

    def test_xiaomi_blocks_taps_explained(self):
        with mock.patch("shutil.which", return_value="/usr/bin/adb"), \
             mock.patch("subprocess.run", return_value=self.proc(err=b"java.lang.SecurityException: Injecting to another "
                                                                      b"application requires INJECT_EVENTS permission", code=0)):
            with self.assertRaises(android.PhoneError) as e:
                android.run(["shell", "input", "tap", "1", "1"])
        self.assertIn("настройки безопасности", str(e.exception))

    def test_keyboard_switch_blocked_explained(self):
        with mock.patch("shutil.which", return_value="/usr/bin/adb"), \
             mock.patch("subprocess.run", return_value=self.proc(err=b"java.lang.SecurityException: uid 2000 does not have "
                                                                      b"android.permission.WRITE_SECURE_SETTINGS.", code=255)):
            with self.assertRaises(android.PhoneError) as e:
                android.run(["shell", "ime", "set", android.ADB_IME])
        self.assertIn("настройки безопасности", str(e.exception))

    def test_no_phone(self):
        with mock.patch.object(android, "run", return_value="List of devices attached\n\n"):
            out = phone.tool_phone({"action": "status"})
        self.assertIn("не подключён", out)

    def test_unauthorized(self):
        with mock.patch.object(android, "run", return_value="List of devices attached\nX1 unauthorized usb:1-4\n"):
            out = phone.tool_phone({"action": "status"})
        self.assertIn("Разрешить отладку", out)

    def test_no_adb(self):
        with mock.patch("shutil.which", return_value=None):
            out = phone.tool_phone({"action": "status"})
        self.assertIn("sudo apt install", out)



class WifiConnect(unittest.TestCase):
    """Подключение по Wi-Fi без вопросов «какой адрес»: телефон сам объявляет себя (adb mdns). Живой случай 10.11.2026:
    Хлоя десять минут пыталась подключиться по старому адресу из памяти и просила назвать цифры голосом."""

    MDNS = ("List of discovered mdns services\n"
            "adb-i7ssc6aqeudmmrz5-AbC\t_adb-tls-connect._tcp.\t192.168.1.6:34711\n"
            "adb-i7ssc6aqeudmmrz5\t_adb-tls-pairing._tcp.\t192.168.1.6:37123\n")

    def fake_run(self, outputs):
        calls = []

        def run(args, timeout=15, binary=False, serial=None):
            calls.append(list(args))
            return outputs.get(args[0], "")
        return run, calls

    def test_discover(self):
        run, _ = self.fake_run({"mdns": self.MDNS})
        with mock.patch.object(android, "run", run):
            self.assertEqual(android.discover(), {"connect": ["192.168.1.6:34711"], "pairing": ["192.168.1.6:37123"]})

    def test_connect_finds_address_itself(self):
        run, calls = self.fake_run({"devices": "List of devices attached\n", "mdns": self.MDNS, "connect": "connected to 192.168.1.6:34711"})
        with mock.patch.object(android, "run", run):
            self.assertIn("192.168.1.6:34711", android.connect())
        self.assertIn(["connect", "192.168.1.6:34711"], calls)

    def test_already_connected_and_not_visible(self):
        run, _ = self.fake_run({"devices": "List of devices attached\nabc\tdevice model:Redmi\n"})
        with mock.patch.object(android, "run", run):
            self.assertIn("уже подключён", android.connect())
        run, _ = self.fake_run({"devices": "List of devices attached\n", "mdns": "List of discovered mdns services\n"})
        with mock.patch.object(android, "run", run):
            with self.assertRaises(android.PhoneError) as c:
                android.connect()
        self.assertIn("Беспроводная отладка", str(c.exception))

    def test_pair_uses_code_and_found_address(self):
        run, calls = self.fake_run({"mdns": self.MDNS, "pair": "Successfully paired to 192.168.1.6:37123 [guid=adb-x]"})
        with mock.patch.object(android, "run", run):
            self.assertIn("сопряжено", android.pair("645 880"))
        self.assertIn(["pair", "192.168.1.6:37123", "645880"], calls)
        with self.assertRaises(android.PhoneError):
            android.pair("6458")                                   # код — шесть цифр
        run, _ = self.fake_run({"mdns": "List of discovered mdns services\n"})
        with mock.patch.object(android, "run", run):
            with self.assertRaises(android.PhoneError):
                android.pair("645880")                              # адреса нет — просим открыть экран сопряжения

    def test_tool_actions(self):
        run, _ = self.fake_run({"devices": "List of devices attached\n", "mdns": self.MDNS, "connect": "connected to 192.168.1.6:34711",
                                "pair": "Successfully paired"})
        with mock.patch.object(android, "run", run):
            self.assertIn("подключила", phone.tool_phone({"action": "connect"}))
            with mock.patch("chloe.tools.phone.confirm", return_value=False):
                self.assertEqual(phone.tool_phone({"action": "pair", "code": "645880"}), "Не сопрягаю.")
            with mock.patch("chloe.tools.phone.confirm", return_value=True):
                self.assertIn("сопряжено", phone.tool_phone({"action": "pair", "code": "645880"}))


if __name__ == "__main__":
    unittest.main()
