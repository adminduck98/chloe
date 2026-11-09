"""Картинки и видео через Qwen: запросы к Alibaba подменены, файлы — во временной папке."""
import json
import pathlib
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

from chloe import qwen_media as qm
from chloe.permissions import permissions
from chloe.tools import HANDLERS
from chloe.tools import media
from chloe.voice import voice

voice.enabled = False


class FakeResp:
    def __init__(self, data):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()

    def read(self, n=-1):
        d, self.data = (self.data, b"") if n < 0 else (self.data[:n], self.data[n:])
        return d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        for name, val in (("IMAGE_DIR", self.dir / "img"), ("VIDEO_DIR", self.dir / "vid")):
            p = mock.patch.object(qm, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(qm.config, "QWEN_KEY", "sk-sp-test")
        p.start()
        self.addCleanup(p.stop)
        self.sent = []

    def fake_urlopen(self, answers):
        def urlopen(req, timeout=None):
            if isinstance(req, str):                       # скачивание готового файла
                return FakeResp(b"FILEDATA")
            self.sent.append((req.get_method(), req.full_url, json.loads(req.data) if req.data else None, dict(req.headers)))
            ans = answers.pop(0)
            if isinstance(ans, Exception):
                raise ans
            return FakeResp(ans)
        return mock.patch("urllib.request.urlopen", side_effect=urlopen)


class Image(Base):
    def test_image_saved(self):
        out = {"output": {"choices": [{"message": {"content": [{"image": "https://x/a.png"}]}}]}}
        with self.fake_urlopen([out]):
            paths = qm.image("кошка на окне", "16:9")
        self.assertEqual(paths[0].read_bytes(), b"FILEDATA")
        self.assertEqual(paths[0].parent, self.dir / "img")
        method, url, body, headers = self.sent[0]
        self.assertTrue(url.startswith("https://token-plan.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/multimodal"))
        self.assertEqual(body["parameters"]["size"], "1664*928")
        self.assertFalse(body["parameters"]["watermark"])
        self.assertEqual(headers["Authorization"], "Bearer sk-sp-test")

    def test_edit_local_image_sent_as_data_uri(self):
        src = self.dir / "in.png"
        src.write_bytes(b"\x89PNG")
        out = {"output": {"choices": [{"message": {"content": [{"image": "https://x/b.png"}]}}]}}
        with self.fake_urlopen([out]):
            qm.image("сделай фон синим", source=str(src))
        content = self.sent[0][2]["input"]["messages"][0]["content"]
        self.assertTrue(content[0]["image"].startswith("data:image/png;base64,"))
        self.assertNotIn("size", self.sent[0][2]["parameters"])

    def test_quota_error_explained(self):
        err = urllib.error.HTTPError("u", 429, "x", {}, mock.Mock(read=lambda: b'{"code":"insufficient_quota","message":"q"}'))
        with self.fake_urlopen([err]), self.assertRaises(qm.MediaError) as c:
            qm.image("кот")
        self.assertIn("кредиты Qwen закончились", str(c.exception))


class Video(Base):
    def test_start_is_async(self):
        with self.fake_urlopen([{"output": {"task_id": "t1", "task_status": "PENDING"}}]):
            self.assertEqual(qm.video_start("волны", seconds=99), "t1")
        _, url, body, headers = self.sent[0]
        self.assertIn("/video-generation/video-synthesis", url)
        self.assertEqual(headers["X-dashscope-async"], "enable")
        self.assertEqual(body["parameters"]["duration"], 15)
        self.assertEqual(body["model"], qm.VIDEO_MODEL)

    def test_wait_downloads(self):
        answers = [{"output": {"task_status": "RUNNING"}},
                   {"output": {"task_status": "SUCCEEDED", "video_url": "https://x/v.mp4"}}]
        with self.fake_urlopen(answers):
            path = qm.video_wait("t1", "волны", sleep=lambda s: None)
        self.assertEqual(path.suffix, ".mp4")
        self.assertTrue(self.sent[0][1].endswith("/api/v1/tasks/t1"))

    def test_wait_failed(self):
        with self.fake_urlopen([{"output": {"task_status": "FAILED", "code": "InvalidParameter", "message": "bad"}}]):
            with self.assertRaises(qm.MediaError):
                qm.video_wait("t1", "x", sleep=lambda s: None)


class Tool(Base):
    def setUp(self):
        super().setUp()
        media.jobs.clear()
        p = mock.patch.object(media, "show")
        self.show = p.start()
        self.addCleanup(p.stop)

    def finish(self):
        for t in threading.enumerate():
            if t is not threading.current_thread() and t.daemon and t.name.startswith("Thread"):
                t.join(5)

    def test_registered(self):
        self.assertIn("create_media", HANDLERS)

    def test_image_in_background_then_announced(self):
        done = threading.Event()
        with mock.patch.object(qm, "image", return_value=[self.dir / "a.png"]), \
                mock.patch.object(media, "_say", side_effect=lambda t: done.set()) as say:
            out = media.tool_create_media({"action": "image", "prompt": "кот"})
            self.assertIn("Начала рисовать", out)
            self.assertTrue(done.wait(5))
        self.assertIn("Картинка готова", say.call_args[0][0])
        self.show.assert_called_once()
        self.assertIn("готово", media.tool_create_media({"action": "status"}))

    def test_video_needs_confirmation(self):
        with mock.patch.object(media, "confirm", return_value=False), mock.patch.object(qm, "video_start") as start:
            self.assertEqual(media.tool_create_media({"action": "video", "prompt": "волны"}), "Не делаю видео.")
        start.assert_not_called()

    def test_missing_source_file(self):
        out = media.tool_create_media({"action": "image", "prompt": "x", "image": str(self.dir / "nope.png")})
        self.assertIn("нет файла", out)

    def test_empty_prompt(self):
        self.assertIn("Нужно описание", media.tool_create_media({"action": "video", "prompt": " "}))

    def test_vault_image_blocked(self):
        with mock.patch.object(permissions, "in_vault", side_effect=lambda p: "secret" in p):
            verdict = permissions.check("create_media", {"action": "image", "prompt": "x", "image": "~/secret/a.png"})
        self.assertEqual(verdict[0], "block")


if __name__ == "__main__":
    unittest.main()
