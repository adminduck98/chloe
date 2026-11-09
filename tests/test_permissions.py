"""Карта прав (DATA PERMISSION MAP) и Private Vault: запрет и вопрос действительно работают, обойти их нельзя."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chloe import config
from chloe.knowledge import knowledge
from chloe.permissions import CATEGORIES, permissions, usage
from chloe.signals import state
from chloe.tools import HANDLERS, run_tool
from chloe.voice import voice

voice.enabled = False   # подтверждения — через подменённый input


def answer(reply):
    return mock.patch("builtins.input", return_value=reply)


class PermissionMap(unittest.TestCase):
    def reset(self):
        permissions.levels = {k: d for k, (_, _, _, d) in CATEGORIES.items()}
        permissions.vault = []
        permissions.save()

    def setUp(self):
        self.reset()
        self.addCleanup(self.reset)   # следующие тесты (погода, файлы…) — с правами по умолчанию
        state["declined"] = False
        state["task_failed"] = {}
        self.home = Path(tempfile.mkdtemp(prefix="perm-", dir=str(config.HOME)))
        self.addCleanup(shutil.rmtree, self.home, True)
        self.vault = self.home / "Личное"
        self.vault.mkdir()
        (self.vault / "паспорт.txt").write_text("серия 1234 номер 567890", encoding="utf-8")
        (self.home / "заметка.txt").write_text("купить хлеб", encoding="utf-8")

    def test_block_stops_the_tool(self):
        permissions.set_level("files_read", "block")
        with mock.patch.dict(HANDLERS, {"read_text_file": mock.Mock(return_value="текст")}) as h:
            out, _, failed = run_tool("read_text_file", {"path": str(self.home / "заметка.txt")})
            HANDLERS["read_text_file"].assert_not_called()
        self.assertTrue(failed)
        self.assertTrue(out.startswith("Отказано"))
        self.assertIn("Не пытайся получить то же другим", out)

    def test_ask_runs_only_after_yes(self):
        permissions.set_level("files_read", "ask")
        with answer("нет"):
            out, _, failed = run_tool("read_text_file", {"path": str(self.home / "заметка.txt")})
        self.assertTrue(failed)
        self.assertNotIn("хлеб", out)
        state["declined"] = False
        with answer("да, делай"):
            out, _, failed = run_tool("read_text_file", {"path": str(self.home / "заметка.txt")})
        self.assertFalse(failed)
        self.assertIn("хлеб", out)

    def test_uncategorized_tools_are_not_affected(self):
        for k in CATEGORIES:
            permissions.set_level(k, "block")
        out, _, failed = run_tool("system_info", {})
        self.assertFalse(failed)

    def test_vault_closes_every_way_in(self):
        permissions.vault_add(self.vault)
        for tool, args in (("read_text_file", {"path": str(self.vault / "паспорт.txt")}),
                           ("list_folder", {"path": str(self.vault)}),
                           ("learn_document", {"path": str(self.vault)}),
                           ("move_path", {"src": str(self.home / "заметка.txt"), "dst": str(self.vault / "x.txt")}),
                           ("run_command", {"command": "cat {}/паспорт.txt".format(self.vault)})):
            out, _, failed = run_tool(tool, args)
            self.assertTrue(failed, tool)
            self.assertIn("Private Vault", out, tool)
        out, _, _ = run_tool("search_files", {"query": "паспорт", "folder": str(self.home)})
        self.assertNotIn("паспорт", out)                                  # поиск внутрь не заглядывает
        self.assertTrue((self.home / "заметка.txt").exists())             # переноса в Vault не было

    def test_vault_hides_already_learned_documents(self):
        for d in knowledge.docs():
            knowledge.forget(d["id"])
        run_tool("learn_document", {"path": str(self.vault)})             # изучено, пока папка была обычной
        self.assertTrue(knowledge.search("паспорт серия"))
        permissions.vault_add(self.vault)
        self.assertEqual(knowledge.search("паспорт серия"), [])           # стала приватной — в ответах нет

    def test_voice_can_tighten_but_loosening_needs_yes(self):
        out, _, _ = run_tool("permissions", {"action": "set", "category": "telegram", "level": "block"})
        self.assertEqual(permissions.level("telegram"), "block")          # усилить — сразу
        with answer("нет"):
            run_tool("permissions", {"action": "set", "category": "telegram", "level": "allow"})
        self.assertEqual(permissions.level("telegram"), "block")          # ослабить без «да» — нельзя
        state["declined"] = False
        with answer("да, делай"):
            run_tool("permissions", {"action": "set", "category": "Telegram", "level": "allow"})
        self.assertEqual(permissions.level("telegram"), "allow")
        run_tool("permissions", {"action": "vault_add", "path": str(self.vault)})
        self.assertTrue(permissions.in_vault(self.vault / "паспорт.txt"))
        state["declined"] = False
        with answer("нет"):
            run_tool("permissions", {"action": "vault_remove", "path": str(self.vault)})
        self.assertTrue(permissions.in_vault(self.vault))                 # убрать из Vault без «да» — нельзя

    def test_show_lists_levels_and_vault(self):
        permissions.vault_add(self.vault)
        out, _, _ = run_tool("permissions", {"action": "show"})
        self.assertIn("Экран — разрешено", out)
        self.assertIn("Питание — разрешено", out)
        self.assertIn("Личное", out)

    def test_vision_obeys_the_map(self):
        from chloe.vision import vision

        self.assertTrue(vision.enabled or True)
        permissions.set_level("screen", "block")
        self.assertFalse(vision.enabled)                                  # постоянного зрения нет
        self.assertIsNone(vision.fresh_frame())
        permissions.set_level("screen", "allow")
        permissions.vault_add(self.vault)
        self.assertIn("Личное", vision.private_words())                   # окна с приватной папкой не смотрит

    def test_saved_and_loaded(self):
        permissions.set_level("commands", "ask")
        permissions.vault_add(self.vault)
        data = json.loads(permissions.path.read_text(encoding="utf-8"))
        self.assertEqual(data["levels"]["commands"], "ask")
        permissions.levels, permissions.vault = {}, []
        permissions.load()
        self.assertEqual(permissions.level("commands"), "ask")
        self.assertTrue(permissions.in_vault(self.vault))

    def test_window_api_and_phone_cannot_change(self):
        from chloe import remote
        from chloe.app import Api

        m = Api().permission_set("internet", "ask")
        self.assertEqual(next(c for c in m["categories"] if c["key"] == "internet")["level"], "ask")
        self.assertIn("error", Api().vault_add(str(self.home / "нет-такой")))
        self.assertIn(str(self.vault.resolve()), Api().vault_add(str(self.vault))["vault"])
        for name in ("permission_set", "vault_add", "vault_remove", "permissions_get"):
            self.assertNotIn(name, remote.ALLOWED)                       # с телефона права не поменять

    def test_usage_is_counted_from_the_journal(self):
        run_tool("read_text_file", {"path": str(self.home / "заметка.txt")})
        self.assertGreaterEqual(usage(1).get("files_read", {}).get("uses", 0), 1)


if __name__ == "__main__":
    unittest.main()
