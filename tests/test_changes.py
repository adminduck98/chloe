"""Изменения файлов и их отмена. Всё — во временной домашней папке, Корзина тоже там."""
import unittest
from unittest import mock

from chloe import config
from chloe.changes import changes
from chloe.tools import run_tool
from chloe.tools.files import replacing
from chloe.voice import voice

voice.enabled = False
HOME = config.HOME


def yes(tool, args):
    with mock.patch("builtins.input", return_value="да, делай"):
        return run_tool(tool, args)


def last_change():
    return changes.list(1)[0]


class Undo(unittest.TestCase):
    def setUp(self):
        self.dir = HOME / "work"
        self.dir.mkdir(exist_ok=True)
        for f in self.dir.iterdir():
            if f.is_file():
                f.unlink()

    def test_new_file_goes_to_trash(self):
        f = self.dir / "new.txt"
        run_tool("write_text_file", {"path": str(f), "content": "привет"})
        ok, _ = changes.undo(last_change()["id"])
        self.assertTrue(ok)
        self.assertFalse(f.exists())
        self.assertTrue(any((HOME / ".local/share/Trash/files").glob("new*.txt")))   # не стёрт — в Корзине

    def test_overwrite_brings_old_version_back(self):
        f = self.dir / "note.txt"
        f.write_text("старый текст")
        yes("write_text_file", {"path": str(f), "content": "новый текст"})
        self.assertEqual(f.read_text(), "новый текст")
        changes.undo(last_change()["id"])
        self.assertEqual(f.read_text(), "старый текст")

    def test_move_back(self):
        a, b = self.dir / "a.pdf", HOME / "work" / "sub"
        a.write_text("pdf")
        run_tool("move_path", {"source": str(a), "destination": str(b / "a.pdf")})
        self.assertFalse(a.exists())
        changes.undo(last_change()["id"])
        self.assertEqual(a.read_text(), "pdf")

    def test_move_onto_existing_restores_both(self):
        a, b = self.dir / "x.txt", self.dir / "y.txt"
        a.write_text("x")
        b.write_text("y")
        yes("move_path", {"source": str(a), "destination": str(b)})
        self.assertEqual(b.read_text(), "x")
        changes.undo(last_change()["id"])
        self.assertEqual((a.read_text(), b.read_text()), ("x", "y"))

    def test_copy_removed(self):
        a = self.dir / "c.txt"
        a.write_text("c")
        run_tool("copy_path", {"source": str(a), "destination": str(self.dir / "c2.txt")})
        changes.undo(last_change()["id"])
        self.assertFalse((self.dir / "c2.txt").exists())
        self.assertTrue(a.exists())

    def test_delete_restored_from_trash(self):
        f = self.dir / "важный отчёт.txt"
        f.write_text("данные")
        yes("delete_path", {"path": str(f)})
        self.assertFalse(f.exists())
        ok, message = changes.undo(last_change()["id"])
        self.assertTrue(ok, message)
        self.assertEqual(f.read_text(), "данные")

    def test_created_folders_removed(self):
        run_tool("create_folder", {"path": str(self.dir / "new1" / "new2")})
        changes.undo(last_change()["id"])
        self.assertFalse((self.dir / "new1").exists())   # убрана вся созданная ветка, а work осталась
        self.assertTrue(self.dir.exists())

    def test_undo_twice_and_by_voice(self):
        f = self.dir / "v.txt"
        run_tool("write_text_file", {"path": str(f), "content": "v"})
        out, _, failed = yes("undo_change", {})   # «Хлоя, отмени последнее»
        self.assertFalse(failed, out)
        self.assertFalse(f.exists())
        self.assertFalse(changes.undo(last_change()["id"])[0])   # второй раз отменять нечего

    def test_failed_operation_puts_old_file_back(self):
        f = self.dir / "keep.txt"
        f.write_text("не потерять")

        def broken():
            raise OSError("диск отвалился")

        with self.assertRaises(OSError):
            replacing(f, broken)
        self.assertEqual(f.read_text(), "не потерять")


if __name__ == "__main__":
    unittest.main()
