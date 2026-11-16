"""Отчёт владельцу: деньги по моделям и за видео, работа по журналу; в понедельник — в утренней сводке."""
import time
import unittest
from unittest import mock

from chloe import media_budget, report, usage
from chloe.settings import settings


class Report(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get(media_budget.KEY)
        settings.set(media_budget.KEY, [])
        self.addCleanup(settings.set, media_budget.KEY, self.saved)

    def test_money_and_text(self):
        day = time.strftime("%Y-%m-%d")
        media_budget.spend("video", 5, "Интернет пропал")
        with mock.patch.object(usage, "load", return_value={day: {"deepseek-flash": {"usd": 0.5}, "claude-haiku-5-5": {"usd": 0.25}}}):
            m = report.money(7)
            txt = report.text(7)
        self.assertAlmostEqual(m["brain_usd"], 0.75)
        self.assertEqual(len(m["videos"]), 1)
        self.assertIn("deepseek-flash $0.50", txt)
        self.assertIn("«Интернет пропал»", txt)
        self.assertIn("$100 в месяц", txt)

    def test_monday_brief_has_report(self):
        import datetime

        from chloe.tools import news as N

        class Monday(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 16, 8, 0)
        with mock.patch.object(N.datetime, "datetime", Monday), mock.patch.object(N, "_part", side_effect=lambda t, f: t):
            out = N.tool_morning_brief({})
        self.assertIn("Отчёт за неделю", out)


if __name__ == "__main__":
    unittest.main()
