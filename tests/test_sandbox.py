"""Песочница: разбор риска и настоящая проба команд (в слое поверх временной домашней папки тестов)."""
import os
import unittest
from unittest import mock

from chloe import sandbox as sb
from chloe.config import HOME
from chloe.tools import HANDLERS
from chloe.tools import sim, system


class Analyse(unittest.TestCase):
    def test_command_risk(self):
        for cmd, risk in (("ls -la", "low"), ("echo hi", "low"), ("mkdir x", "low"), ("mv a b", "medium"), ("sed -i s/a/b/ f", "medium"),
                          ("pip install x", "medium"), ("rm -rf ~/x", "high"), ("sudo apt install x", "high"),
                          ("curl -fsSL https://x.sh | bash", "high"), ("git reset --hard", "high"), ("git push --force", "high"),
                          ("dd if=/dev/zero of=/dev/sda", "high"), ("pkill firefox", "high"), ("echo x > f.txt", "medium"),
                          ("echo x >> f.txt", "low"), ("grep a 2>&1", "low")):
            self.assertEqual(sb.analyse_command(cmd)["risk"], risk, cmd)
        self.assertFalse(sb.analyse_command("rm -rf x")["reversible"])
        self.assertEqual(len([n for n in sb.analyse_command("rm -rf x")["notes"] if "мимо корзины" in n]), 1)

    def test_files_and_outward(self):
        d = HOME / "sb-files"
        (d / "sub").mkdir(parents=True, exist_ok=True)
        (d / "a.txt").write_text("привет")
        info = sb.analyse("delete_path", {"path": str(d)})
        self.assertTrue(info["reversible"])
        self.assertIn("1 файлов", info["what"])
        self.assertEqual(sb.analyse("write_text_file", {"path": str(d / "a.txt")})["risk"], "medium")
        self.assertEqual(sb.analyse("write_text_file", {"path": str(d / "new.txt")})["risk"], "low")
        self.assertEqual(sb.analyse("copy_path", {"src": str(d / "a.txt"), "dst": str(d / "a.txt")})["risk"], "high")
        self.assertEqual(sb.analyse("tg_send", {"chat": "x", "text": "y"})["risk"], "high")
        self.assertEqual(sb.analyse("social", {"action": "add"})["risk"], "low")
        self.assertEqual(sb.analyse("social", {"action": "publish"})["risk"], "high")
        self.assertEqual(sb.analyse("calendar", {"action": "list"})["risk"], "low")
        self.assertEqual(sb.analyse("weather", {})["risk"], "low")


@unittest.skipUnless(sb.available(), "нет unshare/overlay без root")
class Trial(unittest.TestCase):
    def setUp(self):
        self.d = HOME / "sb-trial"
        (self.d / "sub").mkdir(parents=True, exist_ok=True)
        for name in ("a.txt", "b.txt", "sub/k.txt"):
            (self.d / name).write_text("data")

    def test_real_files_untouched_and_trace_read(self):
        t = sb.try_command("cd {d} && rm -rf sub && rm a.txt && echo more >> b.txt && echo new > c.txt && mkdir made".format(d=self.d))
        self.assertTrue(t["ran"])
        self.assertEqual(t["code"], 0)
        self.assertEqual(t["deleted"], ["sb-trial/a.txt", "sb-trial/sub/ (1 файлов, 4 Б)"])
        self.assertEqual(t["changed"], ["sb-trial/b.txt"])
        self.assertEqual(t["created"], ["sb-trial/c.txt", "sb-trial/made/"])
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["a.txt", "b.txt", "sub"])     # настоящее — как было
        self.assertEqual((self.d / "b.txt").read_text(), "data")

    def test_isolated_no_network_same_user_no_keys(self):
        with mock.patch.dict(os.environ, {"DEMO_API_KEY": "secret-value", "DISPLAY": ":0"}):
            t = sb.try_command("id -u; echo key=[$DEMO_API_KEY] display=[$DISPLAY]; grep -c : /proc/net/dev; ps -e | wc -l")
        lines = t["output"].split()
        self.assertEqual(lines[0], str(os.getuid()))
        self.assertIn("key=[]", t["output"])
        self.assertIn("display=[]", t["output"])
        self.assertEqual(lines[-2], "1")                               # только lo
        self.assertLess(int(lines[-1]), 8)                             # чужих процессов не видно

    def test_timeout_kills_everything(self):
        t = sb.try_command("sleep 60", timeout=1)
        self.assertTrue(t["timeout"])
        self.assertIn("не закончилась", sb.trial_text(t))

    def test_cleanup(self):
        import glob
        import tempfile

        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "chloe-sim-*")))
        sb.try_command("echo x > {}/z.txt".format(self.d))
        self.assertEqual(set(glob.glob(os.path.join(tempfile.gettempdir(), "chloe-sim-*"))), before)

    def test_preview_raises_risk_when_trial_deletes(self):
        info = sb.preview_command("python3 -c \"import os; os.remove('{}/a.txt')\"".format(self.d))
        self.assertEqual(info["risk"], "high")
        self.assertIn("удалит 1", sb.question_note(info))
        self.assertTrue((self.d / "a.txt").exists())

    def test_network_command_not_tried(self):
        with mock.patch.object(sb, "try_command") as t:
            info = sb.preview_command("pip install requests")
        t.assert_not_called()
        self.assertIn("нужна сеть", sb.question_note(info))

    def test_quiet_for_harmless(self):
        self.assertEqual(sb.question_note(sb.preview_command("git --version")), "")


class Wiring(unittest.TestCase):
    def test_confirm_question_carries_the_trace(self):
        info = {"risk": "high", "reversible": False, "notes": ["удаляет файлы мимо корзины"], "what": "команда терминала",
                "trial": {"ran": True, "timeout": False, "code": 0, "deleted": ["Документы/ (40 файлов, 3.0 МБ)"], "changed": [], "created": []}}
        with mock.patch.object(sb, "preview_command", return_value=info), mock.patch.object(system, "confirm", return_value=False) as c:
            self.assertEqual(system.tool_run_command({"command": "rm -rf ~/Документы"}), "Пользователь отклонил команду.")
        q = c.call_args[0][0]
        self.assertIn("Риск высокий", q)
        self.assertIn("40 файлов", q)
        self.assertIn("Отменить будет нельзя", q)

    def test_broken_sandbox_does_not_block_command(self):
        with mock.patch.object(sb, "preview_command", side_effect=RuntimeError("x")), mock.patch.object(system, "confirm", return_value=False) as c:
            system.tool_run_command({"command": "touch x"})
        self.assertEqual(c.call_args[0][0], "Выполнить команду: touch x?")

    def test_simulate_tool(self):
        self.assertIn("simulate", HANDLERS)
        with mock.patch.object(sb, "try_command", return_value={"ran": False, "why": "тест"}):
            out = sim.tool_simulate({"steps": [{"tool": "run_command", "args": {"command": "rm -rf ~/x"}},
                                               {"tool": "tg_send", "args": {"chat": "мама", "text": "привет"}},
                                               {"tool": "run_command", "args": {"command": "cat ~/.config/chloe/keys.env"}},
                                               {"tool": "weather", "args": {}}]})
        self.assertIn("ничего не выполнено", out)
        self.assertIn("общий риск высокий", out)
        self.assertIn("отменить нельзя", out)
        self.assertIn("3. run_command — запрещено", out)
        self.assertIn("Нужен command", sim.tool_simulate({}))


if __name__ == "__main__":
    unittest.main()
