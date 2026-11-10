"""Автозапуск (файл .desktop) и одна копия Chloe (файл-замок)."""
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from chloe import autostart


class Desktop(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def test_on_off(self):
        self.assertFalse(autostart.enabled())
        f = autostart.enable()
        self.assertTrue(autostart.enabled())
        text = f.read_text(encoding="utf-8")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn(str(autostart.PROJECT / "start.sh"), text)
        self.assertIn('start.sh" --log', text)
        self.assertIn("X-GNOME-Autostart-Delay=", text)
        self.assertTrue(autostart.disable())
        self.assertFalse(autostart.enabled())
        self.assertFalse(autostart.disable())

    def test_start_script_exists(self):
        self.assertTrue((autostart.PROJECT / "start.sh").is_file())


class OneCopy(unittest.TestCase):
    def test_second_copy_refused(self):
        with tempfile.TemporaryDirectory() as d:
            lock = pathlib.Path(d) / "chloe.lock"
            self.assertTrue(autostart.single_instance(lock))
            self.addCleanup(lambda: autostart._lock and autostart._lock.close())
            code = ("import fcntl,sys; f=open(sys.argv[1],'a+')\n"
                    "try: fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB); print('free')\n"
                    "except OSError: print('busy')")
            out = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True, text=True).stdout.strip()
            self.assertEqual(out, "busy")
            autostart._lock.close()
            out = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True, text=True).stdout.strip()
            self.assertEqual(out, "free")


if __name__ == "__main__":
    unittest.main()
