"""Ключи — в ~/.config/chloe/keys.env (только владелец), а Chloe к этому файлу не прикасается."""
import os
import stat
import unittest
from unittest import mock

from chloe import config
from chloe.permissions import permissions
from chloe.tools import HANDLERS, run_tool


class KeysFile(unittest.TestCase):
    def setUp(self):
        config.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        self.file = config.KEYS_DIR / "keys.env"
        self.addCleanup(self.file.unlink, True)

    def test_parse_formats(self):
        keys = config.parse_keys('# мои ключи\nexport DEEPSEEK_API_KEY="sk-a"\nGEMINI_API_KEY=\'g-b\'\n'
                                 'ANTHROPIC_API_KEY=sk-ant-c\nPATH=/evil\nQWEN_API_KEY=\n')
        self.assertEqual(keys, {"DEEPSEEK_API_KEY": "sk-a", "GEMINI_API_KEY": "g-b", "ANTHROPIC_API_KEY": "sk-ant-c"})

    def test_comment_after_value(self):
        keys = config.parse_keys('export DASHSCOPE_API_KEY="sk-sp-x.y-z_1"   # Qwen (Token Plan)\n'
                                 'GEMINI_API_KEY=g-b  # gemini\nDEEPSEEK_API_KEY="unclosed\n')
        self.assertEqual(keys, {"DASHSCOPE_API_KEY": "sk-sp-x.y-z_1", "GEMINI_API_KEY": "g-b"})

    def test_file_wins_and_gets_private(self):
        self.file.write_text('export DEEPSEEK_API_KEY="sk-new"\n', encoding="utf-8")
        self.file.chmod(0o644)
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-old-from-terminal"}):
            self.assertEqual(config.load_keys(self.file), ["DEEPSEEK_API_KEY"])
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "sk-new")
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)

    def test_missing_file_is_fine(self):
        self.assertEqual(config.load_keys(config.KEYS_DIR / "нет.env"), [])


class ChloeCannotReadKeys(unittest.TestCase):
    def test_file_tools_refuse(self):
        read = mock.Mock(return_value="секрет")
        for path in ("~/.config/chloe/keys.env", str(config.KEYS_DIR), "~/.bashrc.bak-before-qwen", "~/.bailian/config.json", "~/.bailian"):
            with mock.patch.dict(HANDLERS, {"read_file": read}):
                out, _, failed = run_tool("read_file", {"path": path})
            self.assertTrue(failed, path)
        read.assert_not_called()

    def test_commands_refuse(self):
        for cmd in ("cat ~/.config/chloe/keys.env", "printenv", "env", "echo $DEEPSEEK_API_KEY",
                    "cat /proc/self/environ", "grep KEY ~/.bashrc.bak-before-deepseek", "cat ~/.bailian/config.json", "bl auth status", "bl config show"):
            verdict = permissions.check("run_command", {"command": cmd})
            self.assertEqual(verdict[0], "block", cmd)
        self.assertIsNone(permissions.check("run_command", {"command": "ls ~/venv"}))

    def test_bashrc_itself_still_readable(self):
        self.assertFalse(permissions.in_vault("~/.bashrc"))


if __name__ == "__main__":
    unittest.main()
