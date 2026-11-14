"""Бюджет Qwen на медиа: одно видео в неделю, сверх — только по прямой просьбе; черновик не считается;
перед видео — сколько пакета ушло за месяц. Дневные лимиты в долларах для DeepSeek и Claude."""
import time
import unittest
from unittest import mock

from chloe import media_budget as MB
from chloe import usage
from chloe.settings import settings
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False
PLAN = {"title": "Кофе", "scene": "cafe", "beats": [{"words": "Я люблю кофе", "seconds": 3, "motion": "Peach sips"},
                                                   {"words": "а я?", "seconds": 3, "motion": "Puff offended"}]}


class Budget(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get(MB.KEY), settings.get("doodle_draft")
        settings.set(MB.KEY, [])

    def tearDown(self):
        settings.set(MB.KEY, self.saved[0])
        settings.set("doodle_draft", self.saved[1])

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

    def test_cartoon_blocked_but_draft_free(self):
        from chloe import doodle_short as DS

        MB.spend("video", 5, "уже было")
        with mock.patch.object(DS.qm, "available", return_value=True), mock.patch.object(DS, "make_plan", return_value=PLAN), \
                mock.patch("chloe.tools.media.confirm") as ask, mock.patch("chloe.tools.media._start", return_value=7) as start:
            out, _, _ = run_tool("doodle_short", {"idea": "кофе"})
            self.assertIn("Лимит", out)
            ask.assert_not_called()
            out, _, _ = run_tool("doodle_short", {"idea": "кофе", "quality": "draft"})
            self.assertIn("черновик", out)
            self.assertEqual(start.call_args[0][0], "doodle_draft")
            ask.assert_not_called()                                     # черновик бесплатный — без вопроса о цене
            self.assertEqual(settings.get("doodle_draft")["plan"], PLAN)
            ask.return_value = True
            out, _, _ = run_tool("doodle_short", {"from_draft": True, "over_limit": True})
        self.assertIn("480P", ask.call_args[0][0])
        self.assertIn("ушло около", ask.call_args[0][0])
        self.assertEqual(start.call_args[0][0], "doodle")


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
