"""Поиск в интернете: поисковики по очереди — один не ответил или ничего не нашёл, спрашиваем следующий."""
import unittest
from unittest import mock

from chloe.tools import web


class FakeDDGS:
    answers = []
    asked = []

    def __init__(self, timeout=None):
        pass

    def __enter__(self):                     # поиск видео YouTube открывает DDGS через with
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, max_results=6, backend="auto"):
        FakeDDGS.asked.append(backend)
        a = FakeDDGS.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


class TimeoutException(Exception):
    pass


class ByEngine(FakeDDGS):
    """Ответ зависит от поисковика: их спрашивают по два сразу, порядок вызовов не важен."""
    by = {}
    delay = {}

    def text(self, query, max_results=6, backend="auto"):
        import time

        FakeDDGS.asked.append(backend)
        time.sleep(ByEngine.delay.get(backend, 0))
        a = ByEngine.by.get(backend, [])
        if isinstance(a, Exception):
            raise a
        return a


HIT = [{"title": "DV-2027", "href": "https://x", "body": "сроки"}]


class WebSearch(unittest.TestCase):
    def search(self, delay=None, budget=None, **by):
        ByEngine.by, ByEngine.delay, FakeDDGS.asked = by, delay or {}, []
        web._search["good"] = None
        with mock.patch("ddgs.DDGS", ByEngine), mock.patch.object(web, "SEARCH_BUDGET", budget or web.SEARCH_BUDGET):
            return web.tool_web_search({"query": "DV-2027"})

    def test_two_engines_at_once_first_answer_wins(self):
        import time

        started = time.time()
        out = self.search(delay={"bing": 3}, bing=HIT, yandex=[{"title": "быстрый", "href": "https://y", "body": ""}])
        self.assertLess(time.time() - started, 1.5)                # зависший Bing не ждём
        self.assertIn("быстрый", out)
        self.assertEqual(sorted(FakeDDGS.asked), ["bing", "yandex"])
        self.assertEqual(web._search["good"], "yandex")

    def test_remembered_engine_goes_first(self):
        self.search(bing=TimeoutException("молчит"), yandex=HIT)
        self.assertEqual(web._search["good"], "yandex")
        ByEngine.by, FakeDDGS.asked = {"yandex": HIT}, []
        with mock.patch("ddgs.DDGS", ByEngine):
            web.tool_web_search({"query": "ещё"})
        self.assertEqual(FakeDDGS.asked[0], "yandex")               # ответивший — в первой паре

    def test_next_pair_when_first_pair_finds_nothing(self):
        out = self.search(bing=TimeoutException("молчит"), yandex=[], duckduckgo=HIT)
        self.assertIn("DV-2027", out)
        self.assertEqual(web._search["good"], "duckduckgo")

    def test_total_budget_ends_the_search(self):
        import time

        started = time.time()
        with self.assertRaises(RuntimeError):                      # «поисковики не отвечают» — честно, а не «ничего нет»
            self.search(delay={b: 5 for b in web.SEARCH_BACKENDS}, budget=2.0)
        self.assertGreater(time.time() - started, 1.9)             # ждали оба поисковика первой пары
        self.assertLess(time.time() - started, 3.0)                # но не дольше общего предела

    def test_nothing_found_is_an_answer_not_an_error(self):
        out = self.search(bing=Exception("No results found."))
        self.assertIn("Ничего не найдено", out)

    def test_all_engines_silent_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.search(**{b: TimeoutException("молчит") for b in web.SEARCH_BACKENDS})


class PlayYoutube(unittest.TestCase):
    def play(self, videos, page=None):
        opened = []

        def search_page(query, count=5):
            if page is None:
                raise ConnectionError("YouTube не ответил")
            return page

        class Videos(FakeDDGS):
            def videos(self, query, max_results=10):
                a = FakeDDGS.answers.pop(0)
                if isinstance(a, Exception):
                    raise a
                return a

        FakeDDGS.answers = list(videos)
        with mock.patch("ddgs.DDGS", Videos), mock.patch.object(web, "youtube_search_page", search_page), \
             mock.patch("chloe.tools.system.tool_open_url", lambda a: opened.append(a["url"])):
            out = web.tool_play_youtube({"query": "ROSÉ On The Ground"})
        return out, opened

    def test_opens_the_real_video_not_a_guess(self):
        out, opened = self.play([[{"content": "https://vimeo.com/1", "title": "чужое"},
                                  {"content": "https://www.youtube.com/watch?v=CKZvWhCqx1s", "title": "ROSÉ - 'On The Ground' M/V"}]])
        self.assertEqual(opened, ["https://www.youtube.com/watch?v=CKZvWhCqx1s"])
        self.assertIn("On The Ground", out)

    def test_youtube_own_search_comes_first(self):
        out, opened = self.play([], page=[("https://www.youtube.com/watch?v=CKZvWhCqx1s", "ROSÉ - 'On The Ground' M/V")])
        self.assertEqual(opened, ["https://www.youtube.com/watch?v=CKZvWhCqx1s"])

    def test_parses_youtube_results_page(self):
        html = ('..."videoRenderer":{"videoId":"CKZvWhCqx1s","thumbnail":{}, "title":{"runs":[{"text":"ROS\\u00c9 - \'On The Ground\' M/V"}]}...'
                '"videoRenderer":{"videoId":"z6CSW2yu8Mg","title":{"runs":[{"text":"Dance \\"Performance\\""}]}...')
        resp = mock.Mock(text=html, raise_for_status=lambda: None)
        with mock.patch("requests.get", return_value=resp):
            found = web.youtube_search_page("ROSÉ On The Ground")
        self.assertEqual(found[0], ("https://www.youtube.com/watch?v=CKZvWhCqx1s", "ROSÉ - 'On The Ground' M/V"))
        self.assertEqual(found[1][1], 'Dance "Performance"')

    def test_nothing_found_opens_youtube_search(self):
        out, opened = self.play([Exception("No results found."), []])
        self.assertTrue(opened[0].startswith("https://www.youtube.com/results?search_query="))
        self.assertIn("не нашла", out)


if __name__ == "__main__":
    unittest.main()
