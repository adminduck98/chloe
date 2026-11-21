"""Мини-окна «Терминал» и «Файлы»: работают, но правила безопасности (карта прав, Vault, важные папки) — те же."""
import os
import time
import unittest
from unittest import mock

from chloe import config, remote, workbench
from chloe.changes import changes
from chloe.permissions import CATEGORIES, permissions
from chloe.workbench import Terminal


def wait(term, jid, limit=10):
    end = time.time() + limit
    out, off = "", 0
    while time.time() < end:
        r = term.poll(jid, off)
        out += r["out"]
        off = r["offset"]
        if r["done"]:
            return out, r["code"]
        time.sleep(0.05)
    raise AssertionError("команда не закончилась")


class Base(unittest.TestCase):
    def setUp(self):
        permissions.levels = {k: d for k, (_, _, _, d) in CATEGORIES.items()}
        permissions.vault = []
        permissions.save()
        self.root = config.HOME / "wb-test"
        self.root.mkdir(exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)
        permissions.vault = []
        permissions.levels = {k: d for k, (_, _, _, d) in CATEGORIES.items()}
        permissions.save()


class TerminalTest(Base):
    def test_runs_and_streams(self):
        t = Terminal()
        t.cd(str(self.root))
        r = t.start("echo привет && echo мир")
        out, code = wait(t, r["id"])
        self.assertEqual(code, 0)
        self.assertIn("привет", out)
        self.assertIn("мир", out)

    def test_cd_is_remembered(self):
        t = Terminal()
        (self.root / "sub").mkdir()
        self.assertTrue(t.start("cd " + str(self.root)).get("cd"))
        t.start("cd sub")
        self.assertEqual(t.state()["cwd"], str((self.root / "sub").resolve()))
        self.assertIn("error", t.start("cd нет-такой"))
        t.start("cd")
        self.assertEqual(t.state()["cwd"], str(config.HOME.resolve()))

    def test_stop(self):
        t = Terminal()
        r = t.start("sleep 30")
        time.sleep(0.2)
        self.assertTrue(t.stop(r["id"]))
        _, code = wait(t, r["id"], 6)
        self.assertNotEqual(code, 0)

    def test_blocked_by_permission_map(self):
        permissions.set_level("commands", "block")
        self.assertIn("запрещено", Terminal().start("echo 1")["error"])

    def test_vault_folder_closed(self):
        secret = self.root / "Личное"
        secret.mkdir()
        permissions.vault_add(str(secret))
        t = Terminal()
        self.assertIn("приватная", t.start("cd " + str(secret))["error"])

    def test_no_api_keys_in_env(self):
        t = Terminal()
        with mock.patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-секрет", "SOME_TOKEN": "x"}):
            r = t.start("env")
            out, _ = wait(t, r["id"])
        self.assertNotIn("sk-секрет", out)
        self.assertNotIn("SOME_TOKEN", out)

    def test_second_chloe_refused(self):
        self.assertIn("вторая", Terminal().start("./start.sh chloe")["error"])


class FilesTest(Base):
    def test_list_dirs_first_and_hidden(self):
        (self.root / "b.txt").write_text("1")
        (self.root / "a").mkdir()
        (self.root / ".скрытый").write_text("1")
        names = [i["name"] for i in workbench.list_dir(str(self.root))["items"]]
        self.assertEqual(names, ["a", "b.txt"])
        self.assertIn(".скрытый", [i["name"] for i in workbench.list_dir(str(self.root), hidden=True)["items"]])

    def test_vault_not_listed(self):
        secret = self.root / "Личное"
        secret.mkdir()
        (secret / "тайна.txt").write_text("1")
        permissions.vault_add(str(secret))
        r = workbench.list_dir(str(secret))
        self.assertIn("error", r)
        self.assertNotIn("items", r)
        row = [i for i in workbench.list_dir(str(self.root))["items"] if i["name"] == "Личное"][0]
        self.assertTrue(row["private"])

    def test_mkdir_rename_recorded(self):
        before = len(changes.list(500))
        self.assertTrue(workbench.make_dir(str(self.root), "Отчёты")["ok"])
        self.assertTrue(workbench.rename(str(self.root / "Отчёты"), "Отчёты-2025")["ok"])
        self.assertTrue((self.root / "Отчёты-2025").is_dir())
        self.assertEqual(len(changes.list(500)), before + 2)
        self.assertIn("error", workbench.make_dir(str(self.root), "../вне"))
        self.assertIn("error", workbench.rename(str(self.root / "Отчёты-2025"), "a/b"))

    def test_change_blocked(self):
        permissions.set_level("files_change", "block")
        self.assertIn("запрещено", workbench.make_dir(str(self.root), "x")["error"])

    def test_protected_not_trashed(self):
        self.assertIn("error", workbench.trash(str(config.HOME)))
        self.assertIn("error", workbench.rename(str(config.HOME), "другое"))


class RemoteTest(unittest.TestCase):
    def test_phone_cannot_use_workbench(self):
        for name in ("term_start", "term_cd", "files_dir", "files_trash", "files_rename", "files_mkdir", "files_open"):
            self.assertNotIn(name, remote.ALLOWED)


if __name__ == "__main__":
    unittest.main()


class QuickButtonsAndUiTest(unittest.TestCase):
    def setUp(self):
        from chloe.settings import settings

        settings.set("quick_buttons", None)

    def test_defaults_then_add_remove(self):
        from chloe.tools import HANDLERS, run_tool
        from chloe.tools.ui import DEFAULT_BUTTONS, buttons

        self.assertIn("ui", HANDLERS)
        self.assertEqual(len(buttons()), len(DEFAULT_BUTTONS))
        with mock.patch("chloe.tools.ui.brain.js") as js:
            out = HANDLERS["ui"]({"action": "add_button", "label": "Отчёт", "request": "отчёт за неделю"})
            self.assertIn("Отчёт", out)
            js.assert_called_with("chloeUI", {"action": "buttons", "items": buttons()})
            self.assertIn({"label": "Отчёт", "request": "отчёт за неделю"}, buttons())
            HANDLERS["ui"]({"action": "remove_button", "label": "отчёт"})
        self.assertNotIn("Отчёт", [b["label"] for b in buttons()])

    def test_save_cleans_input(self):
        from chloe.tools.ui import MAX_BUTTONS, save_buttons

        with mock.patch("chloe.tools.ui.brain.js"):
            got = save_buttons([{"label": "А", "request": "x"}, {"label": "а", "request": "дубль"}, {"label": "", "request": "y"}, "мусор"] +
                               [{"label": str(i), "request": "z"} for i in range(30)])
        self.assertEqual(got[0], {"label": "А", "request": "x"})
        self.assertEqual(len(got), MAX_BUTTONS)

    def test_open_window_goes_to_page(self):
        from chloe.tools import HANDLERS

        with mock.patch("chloe.tools.ui.brain.js") as js:
            HANDLERS["ui"]({"action": "open", "window": "files", "path": "~/Downloads"})
            js.assert_called_with("chloeUI", {"action": "open", "window": "files", "path": "~/Downloads"})
            self.assertIn("Не знаю", HANDLERS["ui"]({"action": "open", "window": "браузер"}))

    def test_ui_allowed_in_safe_mode(self):
        from chloe.safemode import ALLOWED_TOOLS

        self.assertIn("ui", ALLOWED_TOOLS)   # окно открыть можно и на паузе — оно ничего не меняет

    def test_phone_cannot_change_buttons(self):
        for name in ("quick_buttons_save", "undo_last", "inbox"):
            self.assertNotIn(name, remote.ALLOWED)


class InboxTest(unittest.TestCase):
    def test_question_first_with_answers_and_ready_media(self):
        import time as t

        from chloe import inbox
        from chloe.tools.media import jobs

        jobs[999] = {"kind": "image", "prompt": "обложка", "state": "готово", "result": ["~/a.png"], "started": t.time()}
        try:
            with mock.patch("chloe.actions.waiting", return_value=[{"kind": "question", "what": "Удалить?", "since": t.time()}]):
                items = inbox.collect()
        finally:
            jobs.pop(999, None)
        self.assertEqual(items[0]["group"], "Ждёт ответа")
        self.assertEqual([a["do"] for a in items[0]["actions"]], ["answer", "answer"])
        ready = [i for i in items if i["key"] == "media:999"][0]
        self.assertEqual(ready["actions"][0], {"label": "открыть", "do": "open", "arg": "~/a.png"})
