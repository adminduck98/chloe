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


if __name__ == "__main__":
    unittest.main()
