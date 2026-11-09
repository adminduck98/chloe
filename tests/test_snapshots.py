"""Резервные копии мозга и памяти. Всё во временной домашней папке."""
import json
import shutil
import unittest

from chloe import snapshots
from chloe.app import Api
from chloe.config import BRAIN_FILE, MEMORY_FILE

GOOD = json.dumps({"v": 2, "zones": ["Компьютер"], "neurons": [["Голос", 0, "", 0, 0, 0, 0, 0, 1, 0.5, 0, 1]], "links": []}, ensure_ascii=False)


class Snapshots(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(snapshots.SNAP_DIR, ignore_errors=True)
        BRAIN_FILE.write_text(GOOD, encoding="utf-8")
        MEMORY_FILE.write_text('[{"id": 1, "text": "Любит чёрный кофе", "zone": "Личное"}]', encoding="utf-8")

    def test_daily_copy_on_first_save(self):
        Api().save_brain(GOOD)
        day = snapshots.days()[0]
        names = {p.name for p in (snapshots.SNAP_DIR / day).iterdir()}
        self.assertLessEqual({"brain.json", "memory.json"}, names)

    def test_broken_or_empty_brain_never_overwrites(self):
        self.assertFalse(Api().save_brain('{"neurons": [1, 2'))      # оборвалась запись
        self.assertFalse(Api().save_brain('{"v": 2, "neurons": []}'))  # пустой вместо полного
        self.assertEqual(BRAIN_FILE.read_text(encoding="utf-8"), GOOD)

    def test_reset_keeps_a_copy(self):
        Api().save_brain("")
        self.assertFalse(BRAIN_FILE.exists())
        copy = [d for d in snapshots.days() if "перед-сбросом" in d][0]
        self.assertEqual((snapshots.SNAP_DIR / copy / "brain.json").read_text(encoding="utf-8"), GOOD)

    def test_restore_and_current_is_saved_first(self):
        snapshots.snapshot("2026-11-01")
        BRAIN_FILE.write_text(GOOD.replace("Голос", "Новый"), encoding="utf-8")
        snapshots.restore("2026-11-01")
        self.assertIn("Голос", BRAIN_FILE.read_text(encoding="utf-8"))
        saved = [d for d in snapshots.days() if "перед-восстановлением" in d][0]
        self.assertIn("Новый", (snapshots.SNAP_DIR / saved / "brain.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            snapshots.restore("1999-01-01")

    def test_old_copies_go_away(self):
        for d in ("2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"):
            snapshots.snapshot(d)
        snapshots.daily()
        # старше 14 дней — уходят, но три самые свежие копии дня остаются всегда
        self.assertEqual(snapshots.days()[1:], ["2020-01-04", "2020-01-03"])
        self.assertEqual(len(snapshots.days()), 3)

    def test_last_copies_survive_even_if_all_old(self):
        for d in ("2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"):
            snapshots.snapshot(d)
        snapshots.prune()
        self.assertEqual(snapshots.days(), ["2020-01-04", "2020-01-03", "2020-01-02"])

    def test_reminders_and_journal_are_copied_and_restored(self):
        import sqlite3

        from chloe.config import JOURNAL_FILE
        with sqlite3.connect(JOURNAL_FILE) as c:
            c.execute("create table if not exists snaptest (t text)")
            c.execute("delete from snaptest")
            c.execute("insert into snaptest values ('поздравить маму')")
        self.assertIn("chloe.db", snapshots.snapshot("2026-11-02"))
        with sqlite3.connect(JOURNAL_FILE) as c:
            c.execute("delete from snaptest")
        self.assertIn("chloe.db", snapshots.restore("2026-11-02"))
        with sqlite3.connect(JOURNAL_FILE) as c:
            self.assertEqual(c.execute("select t from snaptest").fetchall(), [("поздравить маму",)])
            c.execute("drop table snaptest")

    def test_learned_skills_are_copied(self):
        skill = snapshots.SKILLS_DIR / "моя-сводка"
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text("Сводка за день", encoding="utf-8")
        try:
            self.assertIn("skills", snapshots.snapshot("2026-11-03"))
            self.assertTrue((snapshots.SNAP_DIR / "2026-11-03" / "skills" / "моя-сводка" / "SKILL.md").exists())
        finally:
            shutil.rmtree(skill)

    def test_broken_file_is_not_copied(self):
        BRAIN_FILE.write_text("{оборвано", encoding="utf-8")
        self.assertNotIn("brain.json", snapshots.snapshot("x"))
        self.assertIn("memory.json", snapshots.snapshot("x"))


if __name__ == "__main__":
    unittest.main()
