"""Поиск в интернете: случайное «No results found» не превращается в сбой шага."""
import unittest
from unittest import mock

from chloe.tools import web


class FakeDDGS:
    answers = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, max_results=6):
        a = FakeDDGS.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


class WebSearch(unittest.TestCase):
    def search(self, *answers):
        FakeDDGS.answers = list(answers)
        with mock.patch("ddgs.DDGS", FakeDDGS):
            return web.tool_web_search({"query": "DV-2027"})

    def test_random_no_results_is_retried(self):
        out = self.search(Exception("No results found."), [{"title": "DV-2027", "href": "https://x", "body": "сроки"}])
        self.assertIn("DV-2027", out)

    def test_empty_twice_is_an_answer_not_an_error(self):
        out = self.search(Exception("No results found."), [])
        self.assertIn("Ничего не найдено", out)

    def test_network_error_still_raises(self):
        with self.assertRaises(ConnectionError):
            self.search(ConnectionError("нет связи"))



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
