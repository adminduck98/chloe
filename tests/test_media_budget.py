"""Бюджет Qwen на медиа: одно видео в неделю, сверх — только по прямой просьбе; черновик не считается;
перед видео — сколько пакета ушло за месяц. Дневные лимиты в долларах для DeepSeek и Claude."""
import time
import unittest
from unittest import mock

from chloe import media_budget as MB
from chloe import usage
from chloe.settings import settings
from chloe.voice import voice

voice.enabled = False


class Budget(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get(MB.KEY)
        settings.set(MB.KEY, [])

    def tearDown(self):
        settings.set(MB.KEY, self.saved)

    def test_one_video_per_week(self):
        self.assertIsNone(MB.video_block())
        MB.spend("video", 5.5, "раз")
        self.assertIn("1 видео в неделю", MB.video_block())
        self.assertIsNone(MB.video_block(over_limit=True))
        MB.spend("image", 0.3, "картинка")
        self.assertAlmostEqual(MB.month_percent(), 5.8)
        self.assertIn("около 6 %", MB.note(5))

    def test_last_week_does_not_count(self):
        MB.spend("video", 5, "старое", now=MB.week_start() - 3600)
        self.assertIsNone(MB.video_block())

    def test_same_film_counts_once(self):
        MB.spend("video", 2, "проба", key="/films/a")
        self.assertIsNone(MB.video_block(key="/films/a"))
        self.assertIsNotNone(MB.video_block(key="/films/b"))


class Refund(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get(MB.KEY)
        settings.set(MB.KEY, [])

    def tearDown(self):
        settings.set(MB.KEY, self.saved)

    def test_failed_video_does_not_take_the_week(self):
        from chloe.tools import media

        at = MB.spend("video", 5, "проба")
        self.assertEqual(MB.week_videos(), 1)                           # пока делается — неделя занята

        def fail():
            raise RuntimeError("кредиты Qwen закончились")
        with self.assertRaises(RuntimeError):
            media._paid(fail, at)()                                     # упал, ничего не сделав
        self.assertEqual(MB.week_videos(), 0)                           # неделя свободна
        self.assertIsNone(MB.video_block())

    def test_spend_and_refund(self):
        at = MB.spend("video", 5, "проба")
        self.assertTrue(MB.refund(at))
        self.assertFalse(MB.refund(at))
        self.assertEqual(MB.month_percent(), 0)


class DayLimit(unittest.TestCase):
    def test_over_limit(self):
        day = time.strftime("%Y-%m-%d")
        data = {day: {"deepseek-flash": {"usd": 0.31}, "claude-haiku-5-5": {"usd": 0.01}}}
        with mock.patch.object(usage, "load", return_value=data), mock.patch.dict("os.environ", {"CHLOE_DAY_LIMIT": "deepseek=0.3,anthropic=0.3"}):
            self.assertEqual(usage.over_limit("deepseek-v4-pro"), ("deepseek", 0.3))
            self.assertIsNone(usage.over_limit("claude-haiku-5-5"))
            self.assertIsNone(usage.over_limit("qwen3.8-flash"))
        with mock.patch.object(usage, "load", return_value=data), mock.patch.dict("os.environ", {"CHLOE_DAY_LIMIT": "off"}):
            self.assertIsNone(usage.over_limit("deepseek-flash"))

    def test_chat_stops_politely_when_all_over(self):
        from chloe.thinking import openai_chat as oc

        with mock.patch.object(oc, "backups", return_value=["deepseek-flash"]), \
                mock.patch.object(usage, "over_limit", return_value=("deepseek", 0.3)):
            msg, model = oc.chat({}, [{"role": "user", "content": "привет"}], "deepseek-flash")
        self.assertEqual(model, oc.LIMIT)
        self.assertIn("лимит", msg.content)


if __name__ == "__main__":
    unittest.main()
