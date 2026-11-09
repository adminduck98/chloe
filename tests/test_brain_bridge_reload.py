"""Окно перезагружается (после «забудь»): события не теряются и не сыплют ошибками, а показываются после загрузки."""
import unittest

from chloe.brain import Brain


class FakeWindow:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, code):
        self.calls.append(code)


class Reload(unittest.TestCase):
    def test_events_wait_while_window_reloads(self):
        b = Brain()
        b.window = FakeWindow()
        b.resume()
        b.js("chloeReply", "до")
        b.pause()                                   # окно перезагружается
        b.js("chloeRemember", "бирюзовый")
        b.js("chloeReply", "Готово")
        self.assertEqual(len(b.window.calls), 1)    # в пустую страницу ничего не ушло
        b.resume()                                  # окно снова готово
        self.assertEqual(len(b.window.calls), 3)
        self.assertIn("chloeRemember", b.window.calls[1])
        self.assertIn("Готово", b.window.calls[2].encode().decode("unicode_escape"))

    def test_expected_reload_that_never_happens_resumes_by_itself(self):
        import time
        b = Brain()
        b.window = FakeWindow()
        b.resume()
        b.expect_reload(0.2)                        # «забудь», но нейрона в окне не было — перезагрузки не будет
        b.js("chloeReply", "Готово")
        self.assertEqual(b.window.calls, [])
        time.sleep(0.4)
        self.assertEqual(len(b.window.calls), 1)    # события не застряли навсегда

    def test_queue_is_bounded(self):
        b = Brain()
        b.window = FakeWindow()
        for i in range(500):
            b.js("chloeState", "idle")
        self.assertEqual(len(b.pending), Brain.PENDING_MAX)


if __name__ == "__main__":
    unittest.main()
