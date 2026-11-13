"""YouTube: статистика канала (только чтение, сеть подменена), пакет к публикации для любого видео, загрузка — через Studio."""
import datetime
import json
import pathlib
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from chloe import google_calendar as gc
from chloe import publish
from chloe import youtube_api as yt
from chloe.tools import run_tool
from chloe.tools import youtube as tyt
from chloe.voice import voice

voice.enabled = False


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.content = data, status, b"x"

    def json(self):
        return self.data


def fake_google(url, params=None, **kw):
    """Ответы YouTube Data API и YouTube Analytics API для одного канала."""
    if url.endswith("/channels"):
        return Resp({"items": [{"id": "UC1", "snippet": {"title": "Мой канал"},
                                "statistics": {"subscriberCount": "1500", "viewCount": "90000", "videoCount": "42"},
                                "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})
    if url.endswith("/playlistItems"):
        return Resp({"items": [{"contentDetails": {"videoId": "v1"}}, {"contentDetails": {"videoId": "v2"}}]})
    if url.endswith("/videos"):
        ids = params["id"].split(",")
        data = {"v1": ("Как я прошёл игру", "PT12M5S", "5000"), "v2": ("Смешной момент", "PT45S", "20000")}
        return Resp({"items": [{"id": i, "snippet": {"title": data[i][0], "publishedAt": "2026-11-01T10:00:00Z"},
                                "contentDetails": {"duration": data[i][1]},
                                "statistics": {"viewCount": data[i][2], "likeCount": "100", "commentCount": "7"}}
                               for i in ids if i in data]})
    if "youtubeanalytics" in url:
        dims = params.get("dimensions")
        if dims == "video":
            return Resp({"columnHeaders": [{"name": "video"}, {"name": "views"}, {"name": "averageViewPercentage"},
                                           {"name": "subscribersGained"}], "rows": [["v2", 20000, 81.5, 30], ["v1", 5000, 42.0, 12]]})
        if dims == "insightTrafficSourceType":
            return Resp({"columnHeaders": [{"name": "insightTrafficSourceType"}, {"name": "views"}],
                         "rows": [["SHORTS", 18000], ["YT_SEARCH", 6000], ["SUGGESTED", 1000]]})
        names = yt.SUMMARY.split(",")
        recent = params["startDate"] >= "2026-10-15"
        row = [25000, 9000, 95, 55.0, 42, 3] if recent else [20000, 6000, 80, 50.0, 30, 5]
        return Resp({"columnHeaders": [{"name": n} for n in names], "rows": [row]})
    raise AssertionError(url)


class Connected(unittest.TestCase):
    def setUp(self):
        gc.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        gc.CLIENT_FILE.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
        yt.TOKEN_FILE.write_text(json.dumps({"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600}))
        self.addCleanup(gc.CLIENT_FILE.unlink, True)
        self.addCleanup(yt.TOKEN_FILE.unlink, True)


class Stats(Connected):
    def test_stats_compare_top_and_traffic(self):
        with mock.patch("chloe.youtube_api.requests.get", side_effect=fake_google) as get:
            s = yt.stats(28, today=datetime.date(2026, 11, 13))
            text = yt.describe_stats(s)
        self.assertEqual((s["from"], s["to"]), ("2026-10-16", "2026-11-12"))   # без сегодняшнего дня
        self.assertIn("«Мой канал»: 1 500 подписчиков", text)
        self.assertIn("просмотры: 25 000 (+25 %", text)
        self.assertIn("время просмотра: 150 ч (+50 %", text)
        self.assertIn("«Смешной момент»: 20 000 просмотров, досматривают 82 %", text)
        self.assertIn("лента Shorts 72 %", text)
        self.assertIn("CTR", text)                                            # честно: CTR — только в Studio
        for call in get.call_args_list:                                        # только чтение и только свой токен
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer tok")

    def test_videos_list(self):
        with mock.patch("chloe.youtube_api.requests.get", side_effect=fake_google):
            out, _, failed = run_tool("youtube", {"action": "videos"})
        self.assertFalse(failed)
        self.assertIn("«Как я прошёл игру» (12:05): 5 000 просмотров", out)
        self.assertIn("«Смешной момент» (0:45)", out)

    def test_api_not_enabled_explained(self):
        err = Resp({"error": {"message": "YouTube Data API v3 has not been used in project 1 before or it is disabled.",
                              "errors": [{"reason": "accessNotConfigured"}]}}, 403)
        with mock.patch("chloe.youtube_api.requests.get", return_value=err):
            out, _, _ = run_tool("youtube", {"action": "stats"})
        self.assertIn("не включён «YouTube Data API v3»", out)

    def test_own_token_not_calendar(self):
        self.assertTrue(yt.connected())
        self.assertFalse(gc.connected())                                      # календарь — отдельный вход


class NotConnectedYet(unittest.TestCase):
    def test_status_tells_what_to_enable(self):
        gc.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        gc.CLIENT_FILE.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
        self.addCleanup(gc.CLIENT_FILE.unlink, True)
        out, _, _ = run_tool("youtube", {"action": "stats"})
        self.assertIn("YouTube Analytics API", out)

    def test_sign_in_asks_read_only_scope_and_saves_own_token(self):
        gc.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        gc.CLIENT_FILE.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}))
        self.addCleanup(gc.CLIENT_FILE.unlink, True)
        self.addCleanup(yt.TOKEN_FILE.unlink, True)
        import threading
        import urllib.parse
        import urllib.request

        seen = {}

        def browser(url):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            seen["scope"] = q["scope"][0]
            threading.Thread(target=lambda: urllib.request.urlopen(
                q["redirect_uri"][0] + "?code=c&state=" + q["state"][0], timeout=5).read(), daemon=True).start()

        tok = Resp({"access_token": "a", "refresh_token": "r", "expires_in": 3600})
        with mock.patch("chloe.google_calendar.requests.post", return_value=tok):
            yt.sign_in(open_browser=browser, wait=10)
        self.assertEqual(seen["scope"].split(), ["https://www.googleapis.com/auth/youtube.readonly",
                                                 "https://www.googleapis.com/auth/yt-analytics.readonly"])
        self.assertTrue(yt.connected())
        self.assertEqual(oct(yt.TOKEN_FILE.stat().st_mode & 0o777), "0o600")


class Chapters(unittest.TestCase):
    def test_youtube_rules(self):
        raw = [[5, "Начало"], [40, "Сборка"], [45, "Слишком близко"], [120, "Итог"], [999, "За концом"]]
        self.assertEqual(publish.clean_chapters(raw, 300), ["0:00 Начало", "0:40 Сборка", "2:00 Итог"])
        self.assertEqual(publish.clean_chapters(raw, 50), [])                  # ролик короче минуты — без глав
        self.assertEqual(publish.clean_chapters([[0, "А"], [30, "Б"]], 300), [])   # меньше трёх глав

    def test_phrases_break_on_pause_and_period(self):
        words = [{"s": 0.0, "e": 0.3, "w": "Привет."}, {"s": 0.4, "e": 0.6, "w": "Сегодня"}, {"s": 0.7, "e": 0.9, "w": "играем"},
                 {"s": 3.0, "e": 3.2, "w": "дальше"}]
        self.assertEqual([p[2] for p in publish.word_phrases(words)], ["Привет.", "Сегодня играем", "дальше"])


class Package(unittest.TestCase):
    def test_any_video_gets_covers_text_and_subtitles(self):
        from chloe import studio

        d = pathlib.Path(tempfile.mkdtemp())
        video = d / "мой ролик.mp4"
        subprocess.run([studio.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=80",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=80", "-shortest", "-pix_fmt", "yuv420p", str(video)],
                       check=True, timeout=120)
        words = [{"s": t, "e": t + 0.5, "w": w} for t, w in ((1, "Сегодня"), (1.6, "собираем"), (2.2, "компьютер."),
                                                             (30, "Ставим"), (30.6, "видеокарту."), (65, "Итог."))]
        reply = json.dumps({"title": "Собрал компьютер за вечер", "description": "Собираю игровой компьютер с нуля.",
                            "tags": ["сборка пк", "компьютер"], "hashtags": ["#пк"],
                            "covers": ["ЗА ОДИН ВЕЧЕР", "ПЕРВЫЙ ЗАПУСК", "ИТОГ"],
                            "chapters": [[0, "Начало"], [28, "Видеокарта"], [63, "Итог"]]}, ensure_ascii=False)
        with mock.patch("chloe.clipper.transcribe", return_value=words), \
                mock.patch("chloe.publish.suggestions", return_value=[]):
            out, report = publish.package_video(video, "сборка ПК", ask=lambda text, think=True: reply, progress=lambda t: None)
        self.assertEqual(out.name, "мой ролик — к публикации")
        self.assertEqual(sorted(p.name for p in out.glob("обложка-*.jpg")), ["обложка-1.jpg", "обложка-2.jpg", "обложка-3.jpg"])
        from PIL import Image

        with Image.open(out / "обложка-1.jpg") as im:
            self.assertEqual(im.size, (1280, 720))
        text = (out / "описание.txt").read_text(encoding="utf-8")
        self.assertIn("Собрал компьютер за вечер", text)
        self.assertIn("0:00 Начало\n0:28 Видеокарта\n1:03 Итог", text)
        self.assertIn("#пк", text)
        self.assertIn("Тестировании и сравнении", text)
        self.assertIn("Видеокарта", text)
        srt = (out / "субтитры.srt").read_text(encoding="utf-8")
        self.assertIn("00:00:01,000 --> ", srt)
        self.assertTrue(any("главы: 3" in r for r in report), report)

    def test_tool_needs_a_real_video(self):
        out, _, _ = run_tool("youtube", {"action": "package", "path": "/нет/такого.mp4"})
        self.assertIn("Нужен путь к видео", out)


class Upload(unittest.TestCase):
    def test_upload_opens_studio_and_never_posts(self):
        with mock.patch("chloe.tools.youtube.webbrowser.open") as web, \
                mock.patch("chloe.youtube_api.requests.get") as get, mock.patch("requests.post") as post:
            out, _, _ = run_tool("youtube", {"action": "upload"})
        web.assert_called_once_with(yt.STUDIO_UPLOAD)
        get.assert_not_called()
        post.assert_not_called()
        self.assertIn("публикует пользователь сам", out)


if __name__ == "__main__":
    unittest.main()
