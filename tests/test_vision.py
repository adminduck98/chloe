"""Постоянное зрение: глаза смотрят на экран в фоне, приватные окна пропускают, кадр и окно доходят до мозга."""
import base64
import unittest

from PIL import Image

from chloe import vision as vision_mod
from chloe.settings import settings
from chloe.tools import TOOLS, run_tool
from chloe.tools import screen
from chloe.vision import Vision, private_title, tool_vision


class Fake:
    """Подменённый экран: заголовок окна и картинка, которые тест меняет сам."""

    def __init__(self):
        self.title = "Visual Studio Code — app.py"
        self.color = (30, 30, 30)
        self.t = 1000.0
        self.grabs = 0

    def capture(self):
        self.grabs += 1
        return Image.new("RGB", (2560, 1440), self.color), 1280   # «ретина»: экран вдвое меньше снимка

    def clock(self):
        return self.t


def make():
    f = Fake()
    return f, Vision(capture=f.capture, title_of=lambda: f.title, clock=f.clock)


class VisionTest(unittest.TestCase):
    def setUp(self):
        settings.set("vision", True)
        settings.set("vision_private", [])

    def test_sees_window_and_frame(self):
        f, v = make()
        v.tick()
        frame = v.fresh_frame()
        self.assertTrue(frame and frame[:2] == b"\xff\xd8")   # JPEG
        img = Image.open(__import__("io").BytesIO(frame))
        self.assertEqual(img.width, 1280)
        self.assertAlmostEqual(screen.state["ratio"], 1.0)   # клик по кадру попадёт в те же точки экрана
        self.assertIn("Visual Studio Code — app.py", v.context())

    def test_same_screen_is_not_reencoded(self):
        f, v = make()
        v.tick()
        first = v.frame
        f.t += 2
        v.tick()
        self.assertIs(v.frame, first)            # экран не менялся — кадр тот же
        self.assertEqual(v.frame_at, f.t)        # но он по-прежнему свежий
        f.color = (220, 220, 220)
        f.t += 2
        v.tick()
        self.assertIsNot(v.frame, first)         # экран сменился — новый кадр

    def test_old_frame_is_not_sent(self):
        f, v = make()
        v.tick()
        f.t += vision_mod.FRESH + 1
        self.assertIsNone(v.fresh_frame())

    def test_private_windows_are_not_seen(self):
        for t in ("Вход в Сбербанк Онлайн", "1Password", "New Incognito Tab - Chrome", "Введите пароль", "Kaspi.kz"):
            self.assertTrue(private_title(t), t)
        for t in ("Visual Studio Code — app.py", "YouTube — Chrome", "Excel — продажи.xlsx"):
            self.assertFalse(private_title(t), t)
        f, v = make()
        v.tick()
        f.title, f.t = "Bitwarden", f.t + 2
        grabs = f.grabs
        v.tick()
        self.assertEqual(f.grabs, grabs)         # снимок даже не делается
        self.assertIsNone(v.fresh_frame())
        self.assertIsNone(v.frame)               # и прошлый кадр забыт
        self.assertIn("приватное окно", v.context())
        self.assertNotIn("Bitwarden", v.context())

    def test_user_hidden_words(self):
        f, v = make()
        settings.set("vision_private", ["Почта"])
        f.title = "Почта — Входящие"
        v.tick()
        self.assertIsNone(v.fresh_frame())

    def test_window_history(self):
        f, v = make()
        for title in ("Chrome — YouTube", "Telegram", "Visual Studio Code — app.py"):
            f.title, f.t = title, f.t + 60
            v.tick()
        ctx = v.context()
        self.assertIn("сейчас активно окно «Visual Studio Code — app.py»", ctx)
        self.assertIn("Telegram", ctx)
        self.assertIn("Chrome — YouTube", ctx)
        self.assertEqual([w for _, w in v.recent()], ["Chrome — YouTube", "Telegram", "Visual Studio Code — app.py"])

    def test_off_means_blind(self):
        f, v = make()
        v.tick()
        v.set_enabled(False)
        self.assertIsNone(v.fresh_frame())
        self.assertEqual(v.context(), "")
        self.assertIsNone(v.frame)
        v.set_enabled(True)

    def test_window_change_is_reported(self):
        f, v = make()
        seen = []
        v.on_window = lambda title, private: seen.append((title, private))
        v.tick()
        f.title = "Пароли — KeePass"
        v.tick()
        self.assertEqual(seen, [("Visual Studio Code — app.py", False), ("Пароли — KeePass", True)])

    def test_voice_tool(self):
        self.assertIn("vision", [t["name"] for t in TOOLS])
        out, err, failed = run_tool("vision", {"action": "off"})
        self.assertFalse(failed)
        self.assertFalse(settings.get("vision"))
        tool_vision({"action": "hide", "word": "WhatsApp"})
        self.assertIn("WhatsApp", settings.get("vision_private"))
        self.assertIn("включено", tool_vision({"action": "on"}))

    def test_frame_goes_into_claude_request(self):
        from chloe.thinking import claude as claude_mod

        f, v = make()
        v.tick()
        old = claude_mod.vision
        claude_mod.vision = v
        try:
            sent = {}

            class Msg:
                stop_reason = "end_turn"
                content = [type("B", (), {"type": "text", "text": "Это ошибка импорта."})()]
                usage = None

            class Client:
                class messages:
                    @staticmethod
                    def create(**kw):
                        sent.update(kw)
                        return Msg()

            class Route:
                model = "claude-haiku"
                def redo_for(self, names): return False
                def check_answer(self, text): return None
                def after_step(self, *a, **k): return None

            messages = []
            try:
                claude_mod.think_claude(Client(), messages, "что это за ошибка?", Route())
            except Exception:
                pass   # нам важно только, что ушло в модель
            first = sent["messages"][0]["content"] if sent else messages[0]["content"]
            self.assertEqual(first[0]["type"], "image")
            self.assertEqual(base64.standard_b64decode(first[0]["source"]["data"])[:2], b"\xff\xd8")
            # следующая просьба — старый кадр из истории убирается, слова остаются
            messages.append({"role": "assistant", "content": [{"type": "text", "text": "ok"}]})
            messages.append({"role": "user", "content": [{"type": "text", "text": "ещё"}]})
            claude_mod.strip_old_images(messages)
            self.assertNotIn("image", [b.get("type") for b in messages[0]["content"]])
            self.assertTrue(any("что это за ошибка" in b.get("text", "") for b in messages[0]["content"]))
        finally:
            claude_mod.vision = old

    def test_openai_history_keeps_words(self):
        from chloe.thinking.openai_chat import forget_old_openai

        messages = [{"role": "system", "content": "s"},
                    {"role": "user", "_vision": True, "content": [{"type": "text", "text": "[12:00] переведи это"},
                                                 {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}]}]
        forget_old_openai(messages)
        self.assertEqual(messages[1]["content"], "[12:00] переведи это [кадр экрана удалён]")


if __name__ == "__main__":
    unittest.main()
