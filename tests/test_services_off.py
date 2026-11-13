"""CHLOE_OFF: выключенный сервис Chloe не зовёт ни мозгом, ни запасным, ни напрямую — его ключ для неё как будто не задан.
Настройки читаются при запуске, поэтому проверка — в отдельном процессе со своим окружением."""
import json
import os
import subprocess
import sys
import unittest

CODE = """
import json
from chloe import config as c
from chloe.thinking import openai_chat as oc
print(json.dumps({"off": sorted(c.OFF), "provider": c.PROVIDER, "fast": c.MODEL_FAST, "strong": c.MODEL_STRONG,
                  "claude": bool(c.ANTHROPIC_KEY), "gemini": bool(c.GEMINI_KEY), "clients": sorted(oc.make_clients()),
                  "chain": oc.backups(c.MODEL_STRONG) + oc.backups(c.MODEL_FAST)}))
"""


def run(**env):
    e = dict(os.environ, DASHSCOPE_API_KEY="q", DEEPSEEK_API_KEY="d", ANTHROPIC_API_KEY="a", GEMINI_API_KEY="g", **env)
    e.pop("CHLOE_MODEL_FAST", None), e.pop("CHLOE_MODEL_STRONG", None)
    if os.environ.get("CHLOE_REAL_HOME"):                   # библиотеки из ~/.local настоящего пользователя (HOME в тестах — временный)
        e["PYTHONUSERBASE"] = os.path.join(os.environ["CHLOE_REAL_HOME"], ".local")
    out = subprocess.run([sys.executable, "-c", CODE], env=e, capture_output=True, text=True, timeout=120,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.stdout.strip(), out.stderr[-800:]
    return json.loads(out.stdout.strip().splitlines()[-1])


class ServicesOff(unittest.TestCase):
    def test_only_qwen_and_deepseek(self):
        r = run(CHLOE_OFF="anthropic, gemini")
        self.assertEqual(r["off"], ["anthropic", "gemini"])
        self.assertFalse(r["claude"] or r["gemini"])
        self.assertEqual((r["provider"], r["fast"], r["strong"]), ("qwen", "qwen3.8-flash", "qwen3.8-flash+thinking"))
        self.assertEqual(r["clients"], ["deepseek", "qwen"])
        self.assertFalse(any(m.startswith(("claude", "gemini")) for m in r["chain"]))

    def test_without_switch_claude_helps(self):
        r = run(CHLOE_OFF="")
        self.assertTrue(r["claude"])
        self.assertEqual(r["strong"], "claude-haiku-5-5")

    def test_unknown_names_ignored(self):
        self.assertEqual(run(CHLOE_OFF="openai, anthropic")["off"], ["anthropic"])


if __name__ == "__main__":
    unittest.main()
