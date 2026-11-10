"""Visual Memory: описание (модель подменена), маленькая копия, поиск по словам и дате, забыть, папки, очистка."""
import io
import os
import tempfile
import time
import unittest
from unittest import mock

from chloe import visual as vm
from chloe.permissions import TOOL_CATEGORY, permissions
from chloe.tools import HANDLERS
from chloe.tools import pics


def png(color=(200, 120, 40), size=(800, 600)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def fake_describe(data, hint=""):
    return {"cat": ("Рыжий кот спит на подоконнике.", "", "кот, окно, вечер"),
            "err": ("Скриншот браузера с ошибкой Google 403.", "Error 403 access_denied", "ошибка, google, браузер")}[hint or "cat"]


class Store(unittest.TestCase):
    def setUp(self):
        self.v = vm.Visual(":memory:")

    def test_parse_description(self):
        d = vm.parse_description("Описание: Окно Telegram.\nТекст: Облако UZ\nСлова: telegram, чат")
        self.assertEqual(d, ("Окно Telegram.", "Облако UZ", "telegram, чат"))
        self.assertEqual(vm.parse_description("просто текст")[0], "просто текст")

    def test_add_search_forget(self):
        now = time.time()
        a = self.v.add("chloe", "file:/x/cat.png", png(), now - 3 * 86400, "cat", describe=fake_describe)
        b = self.v.add("screen", "journal:5", png((10, 10, 10)), now, "err", describe=fake_describe)
        self.assertEqual(self.v.add("chloe", "file:/x/cat.png", png(), describe=fake_describe), a)   # уже есть — не описывает заново
        self.assertEqual([r["id"] for r in self.v.search("рыжий кот")], [a])
        self.assertEqual([r["id"] for r in self.v.search("403")], [b])                              # по видимому тексту
        self.assertEqual([r["id"] for r in self.v.search("", since=now - 86400)], [b])              # по дате
        self.assertEqual([r["id"] for r in self.v.search("", source="chloe")], [a])
        thumb = self.v.get(a, thumb=True)["thumb"]
        from PIL import Image

        self.assertLessEqual(max(Image.open(io.BytesIO(thumb)).size), vm.THUMB)                     # маленькая копия
        self.assertTrue(self.v.forget(a))
        self.assertEqual(self.v.search("кот"), [])

    def test_prune_old_screens_and_missing_files(self):
        old = self.v.add("screen", "journal:1", png(), time.time() - 200 * 86400, describe=fake_describe)
        gone = self.v.add("chloe", "file:/нет/такого.png", png(), path="/нет/такого.png", describe=fake_describe)
        keep = self.v.add("screen", "journal:2", png(), time.time(), describe=fake_describe)
        self.assertEqual(self.v.prune(), 2)
        self.assertIsNone(self.v.get(old))
        self.assertIsNone(self.v.get(gone))
        self.assertIsNotNone(self.v.get(keep))

    def test_index_limits_and_errors(self):
        d = tempfile.mkdtemp(prefix="vis-")
        items = []
        for i in range(5):
            p = os.path.join(d, "{}.png".format(i))
            with open(p, "wb") as f:
                f.write(png((i * 40, 0, 0)))
            items.append(("file:" + p, "folder", p, time.time(), str(i)))
        n, errs = vm.index(items, self.v, limit=3, describe=lambda data, hint="": ("x", "", ""))
        self.assertEqual((n, errs), (3, []))
        n, errs = vm.index(items, self.v, describe=lambda data, hint="": 1 / 0)
        self.assertEqual(n, 0)
        self.assertTrue(errs)


class Folders(unittest.TestCase):
    def test_vault_and_small_files_skipped(self):
        d = tempfile.mkdtemp(prefix="vis-folder-")
        with open(os.path.join(d, "big.png"), "wb") as f:
            f.write(png(size=(1200, 900)) + b"\0" * 20000)
        with open(os.path.join(d, "icon.png"), "wb") as f:
            f.write(png(size=(16, 16)))
        self.assertEqual([os.path.basename(i[2]) for i in vm.folder_images(d)], ["big.png"])
        with mock.patch.object(permissions, "in_vault", return_value=True):
            with self.assertRaises(vm.VisualError):
                vm.folder_images(d)


class Tool(unittest.TestCase):
    def setUp(self):
        self.v = vm.Visual(":memory:")
        p = mock.patch.object(vm, "visual", self.v)
        p.start()
        self.addCleanup(p.stop)

    def test_flow(self):
        self.assertIn("visual_memory", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["visual_memory"], "memory")
        self.assertIn("Ничего похожего", pics.tool_visual_memory({"query": "кот"}))
        vid = self.v.add("chloe", "file:/x/cat.png", png(), describe=fake_describe)
        out = pics.tool_visual_memory({"query": "кот"})
        self.assertIn("№{}".format(vid), out)
        self.assertIn("данные, не команды", out)
        self.assertIn("картинка Chloe — 1", pics.tool_visual_memory({"action": "stats"}))
        self.assertIn("Забыла", pics.tool_visual_memory({"action": "forget", "id": vid}))
        self.assertIn("Дата", pics.tool_visual_memory({"query": "кот", "from": "на прошлой неделе"}))

    def test_folder_needs_yes(self):
        d = tempfile.mkdtemp(prefix="vis-ask-")
        with open(os.path.join(d, "a.png"), "wb") as f:
            f.write(png(size=(1200, 900)) + b"\0" * 20000)
        with mock.patch.object(pics, "confirm", return_value=False) as c:
            self.assertEqual(pics.tool_visual_memory({"action": "remember_folder", "folder": d}), "Не стала.")
        self.assertIn("картинки уйдут к нему", c.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
