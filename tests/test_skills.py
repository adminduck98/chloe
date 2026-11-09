"""Навыки в формате Claude (SKILL.md): чтение, подсказка, инструменты, нейроны, установка. Всё во временной домашней папке."""
import pathlib
import unittest
from unittest import mock

from chloe import config, skillbook
from chloe.brain import brain
from chloe.thinking.prompt import system_prompt
from chloe.thinking.router import Route
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False


def make_skill(root, folder, head, body="Делай так.", files=None):
    d = pathlib.Path(root) / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("---\n" + head + "\n---\n\n" + body, encoding="utf-8")
    for name, text in (files or {}).items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")
    return d


class Skills(unittest.TestCase):
    def setUp(self):
        import shutil

        shutil.rmtree(skillbook.USER_DIR, ignore_errors=True)
        make_skill(skillbook.USER_DIR, "pdf-tools", "name: pdf\ndescription: >\n  Работа с PDF: склеить,\n  разделить, достать текст.",
                   "# PDF\nЗапусти scripts/merge.py.", {"scripts/merge.py": "print('merge')", "REFERENCE.md": "справка"})

    def test_parse_and_prompt(self):
        s = skillbook.get("pdf")
        self.assertEqual(s["description"], "Работа с PDF: склеить, разделить, достать текст.")
        prompt = system_prompt()
        self.assertIn("- pdf: Работа с PDF", prompt)
        self.assertIn("- morning-brief: Утренняя сводка", prompt)   # встроенный навык из папки проекта
        self.assertNotIn("Запусти scripts/merge.py", prompt)       # полная инструкция — только по запросу

    def test_use_skill_gives_body_files_and_path(self):
        out, _, failed = run_tool("use_skill", {"name": "PDF"})
        self.assertFalse(failed, out)
        self.assertIn("Запусти scripts/merge.py", out)
        self.assertIn("Файлы навыка (читать — read_skill_file, запускать скрипты — run_command с полным путём): REFERENCE.md, scripts/merge.py", out)
        self.assertIn(str(skillbook.USER_DIR / "pdf-tools"), out)
        self.assertIn("правила безопасности", out)

    def test_read_file_stays_inside(self):
        self.assertEqual(run_tool("read_skill_file", {"name": "pdf", "path": "REFERENCE.md"})[0], "справка")
        self.assertEqual(run_tool("read_skill_file", {"name": "pdf", "path": "reference.MD"})[0], "справка")   # регистр не важен
        out, _, failed = run_tool("read_skill_file", {"name": "pdf", "path": "../../memory.json"})
        self.assertTrue(failed)

    def test_unknown_skill_lists_known(self):
        out, _, failed = run_tool("use_skill", {"name": "excel"})
        self.assertTrue(failed)
        self.assertIn("pdf", out)

    def test_skill_is_its_own_neuron(self):
        calls = []
        with mock.patch.object(brain, "js", side_effect=lambda fn, *a: calls.append((fn,) + a)):
            run_tool("use_skill", {"name": "pdf"})
        self.assertIn(("chloeUse", "pdf"), calls)

    def test_strong_brain_follows_skill(self):
        config.MODEL_FAST, config.MODEL_STRONG = "fast-model", "strong-model"
        r = Route("склей два pdf")
        self.assertTrue(r.redo_for(["use_skill"]))

    def test_add_from_folder_and_update(self):
        src = make_skill(pathlib.Path(config.HOME) / "downloads-skills" / "repo" / "skills", "x", "name: excel-helper\ndescription: Таблицы")
        self.assertEqual(skillbook.add(str(src.parent.parent)), ["excel-helper"])
        self.assertIsNotNone(skillbook.get("excel-helper"))
        (src / "SKILL.md").write_text("---\nname: excel-helper\ndescription: Таблицы v2\n---\nновое", encoding="utf-8")
        skillbook.add(str(src))
        self.assertEqual(skillbook.get("excel-helper")["description"], "Таблицы v2")

    def test_add_rejects_empty(self):
        empty = pathlib.Path(config.HOME) / "empty-dir"
        empty.mkdir(exist_ok=True)
        with self.assertRaises(ValueError):
            skillbook.add(str(empty))


if __name__ == "__main__":
    unittest.main()
