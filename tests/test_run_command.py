import unittest
from unittest import mock

from chloe.tools import system


class CleanCommand(unittest.TestCase):
    def test_html_entities_unescaped(self):
        self.assertEqual(system.clean_command("cd ~/x &amp;&amp; ls &gt; out"), "cd ~/x && ls > out")

    def test_plain_command_untouched(self):
        self.assertEqual(system.clean_command("echo 'a & b'"), "echo 'a & b'")

    def test_confirm_sees_clean_command(self):
        with mock.patch.object(system, "confirm", return_value=False) as c:
            system.tool_run_command({"command": "touch a &amp;&amp; touch b"})
        self.assertIn("touch a && touch b", c.call_args[0][0])


class SelfStart(unittest.TestCase):
    def test_blocks_own_start(self):
        for cmd in ("cd ~/chloe-main && ./start.sh", "~/chloe-main/start.sh",
                    "cd /home/duck/chloe-main; .venv/bin/python run.py", "bash ~/chloe-main/start.sh &"):
            self.assertTrue(system.starts_chloe(cmd), cmd)

    def test_bare_start_in_project_dir(self):
        with mock.patch("os.getcwd", return_value=system.PROJECT):
            self.assertTrue(system.starts_chloe("./start.sh"))

    def test_other_projects_allowed(self):
        with mock.patch("os.getcwd", return_value="/tmp"):
            self.assertFalse(system.starts_chloe("./start.sh"))
        self.assertFalse(system.starts_chloe("cd ~/other && ./start.sh"))
        self.assertFalse(system.starts_chloe("grep restart.sh notes.txt"))
        self.assertFalse(system.starts_chloe("ls ~/chloe-main"))

    def test_tool_refuses_without_asking(self):
        with mock.patch.object(system, "confirm") as c, mock.patch("subprocess.run") as run:
            out = system.tool_run_command({"command": "cd ~/chloe-main &amp;&amp; ./start.sh"})
        c.assert_not_called()
        run.assert_not_called()
        self.assertIn("вторая Хлоя", out)


if __name__ == "__main__":
    unittest.main()
