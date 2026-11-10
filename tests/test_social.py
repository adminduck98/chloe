"""Соцсети: план, черновики, одобрение, публикация в Telegram (подменён), пакеты для Instagram/YouTube/TikTok."""
import pathlib
import tempfile
import threading
import time
import unittest
from unittest import mock

from chloe import social as sc
from chloe.permissions import TOOL_CATEGORY, permissions
from chloe.social import Social, SocialError
from chloe.tools import HANDLERS
from chloe.tools import social as ts


class FakeTG:
    def __init__(self, kind="канал"):
        self.sent = []
        self.kind = kind

    def ready(self):
        return True

    def dialogs(self):
        return [{"id": 7, "name": "Мой канал", "kind": self.kind, "unread": 0, "muted": False}]

    def run(self, fn, timeout=30):
        import asyncio

        tg = self

        class Client:
            async def send_message(self, chat, text):
                tg.sent.append(("text", chat, text))

            async def send_file(self, chat, files, caption=None, supports_streaming=False):
                tg.sent.append(("file", chat, files, caption))

        return asyncio.run(fn(Client()))


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.img = self.dir / "a.png"
        self.img.write_bytes(b"\x89PNG")
        self.vid = self.dir / "v.mp4"
        self.vid.write_bytes(b"MP4")
        self.s = Social(":memory:")
        for target, name, val in ((ts, "social", self.s), (sc, "EXPORT_DIR", self.dir / "posts")):
            p = mock.patch.object(target, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.tg = FakeTG()
        p = mock.patch("chloe.telegram.telegram", self.tg)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("chloe.tools.tg.telegram", self.tg)
        p.start()
        self.addCleanup(p.stop)


class Rules(Base):
    def test_network_rules(self):
        self.assertEqual(sc.network("Инстаграм"), "instagram")
        with self.assertRaises(SocialError):
            self.s.add("instagram", "Без картинки")
        with self.assertRaises(SocialError):
            self.s.add("youtube", "Без ролика", media=[str(self.img)])
        with self.assertRaises(SocialError):
            self.s.add("telegram", "Без канала")
        with self.assertRaises(SocialError):
            self.s.add("instagram", "#a " * 31, media=[str(self.img)])
        with self.assertRaises(SocialError):
            self.s.add("telegram", "x" * 5000, channel="Мой канал")
        with self.assertRaises(SocialError):
            self.s.add("instagram", "Нет файла", media=[str(self.dir / "nope.png")])

    def test_vault_media_refused(self):
        with mock.patch.object(permissions, "in_vault", return_value=True):
            with self.assertRaises(SocialError):
                self.s.add("instagram", "Пост", media=[str(self.img)])

    def test_edit_resets_approval(self):
        p = self.s.add("telegram", "Текст", channel="Мой канал", due=time.time() + 3600)
        self.s.set_status(p["id"], "approved")
        self.assertEqual(self.s.update(p["id"], due=time.time() + 7200)["status"], "approved")   # только время — согласие в силе
        self.assertEqual(self.s.update(p["id"], text="Другой текст")["status"], "draft")


class Tool(Base):
    def test_registered(self):
        self.assertIn("social", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["social"], "social")

    def test_add_plan_nothing_published(self):
        out = ts.tool_social({"action": "add", "posts": [
            {"network": "telegram", "channel": "Мой канал", "text": "Привет, канал!", "when": "2030-01-01T10:00"},
            {"network": "instagram", "text": "Кошка #кот", "media": [str(self.img)]}]})
        self.assertIn("черновиками (2)", out)
        self.assertEqual(self.tg.sent, [])
        self.assertIn("Instagram", ts.tool_social({"action": "list"}))

    def test_publish_telegram_asks_then_sends(self):
        p = self.s.add("telegram", "Пост с картинкой", channel="мой канал", media=[str(self.img)])
        with mock.patch.object(ts, "confirm", return_value=False):
            self.assertEqual(ts.tool_social({"action": "publish", "id": p["id"]}), "Не публикую.")
        self.assertEqual(self.tg.sent, [])
        with mock.patch.object(ts, "confirm", return_value=True):
            self.assertIn("Опубликовала в канале «Мой канал»", ts.tool_social({"action": "publish", "id": p["id"]}))
        self.assertEqual(self.tg.sent, [("file", 7, str(self.img), "Пост с картинкой")])
        self.assertEqual(self.s.get(p["id"])["status"], "published")

    def test_long_caption_goes_separately(self):
        p = self.s.add("telegram", "д" * 1500, channel="Мой канал", media=[str(self.img)])
        sc.publish_telegram(p, self.tg)
        self.assertEqual([s[0] for s in self.tg.sent], ["file", "text"])
        self.assertIsNone(self.tg.sent[0][3])

    def test_not_a_channel(self):
        self.tg.kind = "личный"
        p = self.s.add("telegram", "Текст", channel="Мой канал")
        with mock.patch.object(ts, "confirm", return_value=True):
            self.assertIn("не канал", ts.tool_social({"action": "publish", "id": p["id"]}))
        self.assertEqual(self.s.get(p["id"])["status"], "failed")

    def test_instagram_package(self):
        p = self.s.add("instagram", "Кошка спит #кот", media=[str(self.img)])
        with mock.patch("webbrowser.open") as web, mock.patch("subprocess.Popen"):
            out = ts.tool_social({"action": "publish", "id": p["id"]})
        self.assertIn("Пакет для Instagram готов", out)
        web.assert_called_once_with(sc.UPLOAD["instagram"])
        folder = pathlib.Path(self.s.get(p["id"])["result"])
        self.assertEqual((folder / "подпись.txt").read_text(encoding="utf-8").strip(), "Кошка спит #кот")
        self.assertTrue((folder / "01.png").is_file())
        self.assertIn("Отметила", ts.tool_social({"action": "done", "id": p["id"]}))

    def test_approve_requires_time_and_yes(self):
        p = self.s.add("telegram", "Текст", channel="Мой канал")
        self.assertIn("Сначала время", ts.tool_social({"action": "approve", "id": p["id"]}))
        ts.tool_social({"action": "edit", "id": p["id"], "when": "2030-01-01T10:00"})
        with mock.patch.object(ts, "confirm", return_value=True) as c:
            self.assertIn("Одобрен", ts.tool_social({"action": "approve", "id": p["id"]}))
        self.assertIn("Запланировать", c.call_args[0][0])


class Watcher(Base):
    def run_once(self):
        said = []
        stop = threading.Event()

        def say(text):
            said.append(text)
            stop.set()

        t = threading.Thread(target=ts.watcher, args=(say, 0.01, stop))
        t.start()
        t.join(5)
        stop.set()
        return said

    def test_approved_goes_out_by_itself(self):
        p = self.s.add("telegram", "По расписанию", channel="Мой канал", due=time.time() - 1)
        self.s.set_status(p["id"], "approved")
        said = self.run_once()
        self.assertIn("Опубликовала", said[0])
        self.assertEqual(self.tg.sent[0][2], "По расписанию")

    def test_unapproved_only_reminds(self):
        p = self.s.add("telegram", "Не одобрен", channel="Мой канал", due=time.time() - 1)
        said = self.run_once()
        self.assertIn("не одобрен", said[0])
        self.assertEqual(self.tg.sent, [])
        self.assertIsNone(self.s.get(p["id"])["due"])                 # не напоминает каждую минуту

    def test_instagram_due_makes_package(self):
        self.s.add("instagram", "Пост", media=[str(self.img)], due=time.time() - 1)
        with mock.patch("webbrowser.open"), mock.patch("subprocess.Popen"):
            said = self.run_once()
        self.assertIn("Пора выложить пост в Instagram", said[0])


if __name__ == "__main__":
    unittest.main()
