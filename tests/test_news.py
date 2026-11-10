"""Новости и утренняя сводка: ленты подменены, сеть не нужна."""
import time
import unittest
from unittest import mock

from chloe import news
from chloe.permissions import TOOL_CATEGORY
from chloe.settings import settings
from chloe.tools import HANDLERS
from chloe.tools import news as tn

NOW = 1794300000.0


def rss(*items):
    body = "".join("<item><title>{}</title><link>https://x/{}</link><description>&lt;p&gt;{}&lt;/p&gt;</description>"
                   "<pubDate>{}</pubDate></item>".format(t, i, d, time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(w)))
                   for i, (t, d, w) in enumerate(items))
    return ("<?xml version='1.0'?><rss><channel>" + body + "</channel></rss>").encode()


class Parse(unittest.TestCase):
    def test_rss(self):
        items = news.parse(rss(("[Перевод] Заголовок &amp; ещё", "Описание", NOW)), "Хабр")
        self.assertEqual(items[0]["title"], "Заголовок & ещё")
        self.assertEqual(items[0]["summary"], "Описание")
        self.assertAlmostEqual(items[0]["when"], NOW, delta=1)
        self.assertEqual(items[0]["source"], "Хабр")

    def test_atom(self):
        xml = (b"<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Atom</title><link href='https://a/1'/>"
               b"<updated>2026-11-10T09:00:00Z</updated><summary>s</summary></entry></feed>")
        item = news.parse(xml, "A")[0]
        self.assertEqual((item["title"], item["link"]), ("Atom", "https://a/1"))
        self.assertIsNotNone(item["when"])

    def test_broken_xml(self):
        self.assertEqual(news.parse(b"<rss><item>", "x"), [])


class Headlines(unittest.TestCase):
    def setUp(self):
        news._cache.clear()
        feeds = {
            "https://a": rss(("Центробанк Узбекистана снизил ключевую ставку до 13 процентов", "", NOW - 600),
                             ("Старая новость позавчера", "", NOW - 3 * 86400)),
            "https://b": rss(("ЦБ Узбекистана снизил ключевую ставку до 13 процентов годовых", "", NOW - 300),
                             ("В Ташкенте открыли новую станцию метро", "", NOW - 60)),
            "https://c": b"",
        }

        def get(url, **kw):
            r = mock.Mock(content=feeds[url])
            r.raise_for_status = mock.Mock()
            return r

        p = mock.patch.object(news.requests, "get", side_effect=get)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(news.FEEDS, {"тест": [("A", "https://a"), ("B", "https://b"), ("C", "https://c")]})
        p.start()
        self.addCleanup(p.stop)

    def test_same_story_merged_and_ranked_first(self):
        items, failed = news.headlines("тест", now=NOW)
        self.assertEqual(len(items), 2)                               # старая отброшена, одна новость из двух мест
        self.assertEqual(items[0]["sources"], ["B", "A"])             # о ней пишут двое — выше свежей одиночной
        self.assertIn("метро", items[1]["title"])
        self.assertEqual(failed, ["C"])

    def test_cache(self):
        news.headlines("тест", now=NOW)
        news.headlines("тест", now=NOW + 60)
        self.assertEqual(news.requests.get.call_count, 3)            # второй раз — из кеша

    def test_same_story_rule(self):
        w = news.words
        self.assertTrue(news.same_story(w("ЦБ снизил ключевую ставку до 13%"), w("Центробанк снизил ключевую ставку до 13% годовых")))
        self.assertFalse(news.same_story(w("Главком НАТО участвует в переговорах в Абу-Даби"),
                                         w("Мединский поблагодарил ОАЭ на переговорах в Абу-Даби")))


class Tools(unittest.TestCase):
    def setUp(self):
        for k in ("news_topics", "morning_brief", "brief_day"):
            settings.set(k, None)

    def test_registered(self):
        for name in ("news", "morning_brief"):
            self.assertIn(name, HANDLERS)
            self.assertEqual(TOOL_CATEGORY[name], "news")

    def test_topics_saved(self):
        self.assertIn("Запомнила", tn.tool_news({"action": "topics", "topics": ["мир", "IT"]}))
        self.assertEqual(news.topics(), ["главное", "технологии"])
        self.assertIn("Темы:", tn.tool_news({"action": "topics", "topics": ["котики"]}))

    def test_headlines_marked_as_data(self):
        with mock.patch.object(news, "headlines", return_value=([{"title": "T", "summary": "", "when": None, "sources": ["S"]}], [])):
            out = tn.tool_news({"topic": "главное"})
        self.assertTrue(out.startswith(news.DATA_NOTE))
        self.assertIn("• T (S)", out)
        self.assertIn("Таких тем нет", tn.tool_news({"topic": "котики"}))

    def test_brief_survives_broken_parts(self):
        with mock.patch.object(tn, "_weather", side_effect=RuntimeError("нет сети")), \
                mock.patch.object(tn, "_calendar", return_value=""), \
                mock.patch.object(tn, "_today_reminders", return_value="Напоминания на сегодня: нет"), \
                mock.patch.object(tn, "tool_news", return_value="НОВОСТИ"):
            out = tn.tool_morning_brief({})
        self.assertIn("Погода: не получилось", out)
        self.assertIn("НОВОСТИ", out)
        self.assertIn("утренняя сводка", out)

    def test_morning_due_once_in_the_morning(self):
        morning = time.mktime(time.strptime("2026-11-10 08:00", "%Y-%m-%d %H:%M"))
        self.assertFalse(tn.morning_due(morning))                    # выключено
        tn.tool_news({"action": "morning_on"})
        self.assertFalse(tn.morning_due(morning - 4 * 3600))         # 4 утра — рано
        self.assertTrue(tn.morning_due(morning))
        self.assertFalse(tn.morning_due(morning + 600))              # второй раз за утро — нет
        self.assertTrue(tn.morning_due(morning + 86400))             # завтра — снова
        self.assertFalse(tn.morning_due(morning + 86400 + 6 * 3600)) # 14:00 — уже не утро


if __name__ == "__main__":
    unittest.main()
