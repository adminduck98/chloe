"""Voice Studio: текст и книги → mp3. Голос подменён; склейка — настоящим ffmpeg, если он есть."""
import pathlib
import tempfile
import threading
import unittest
import zipfile
from unittest import mock

from chloe import audiobook as ab
from chloe import studio
from chloe.permissions import TOOL_CATEGORY, permissions
from chloe.tools import HANDLERS
from chloe.tools import media
from chloe.voice import voice

voice.enabled = False
ab.BACKOFF = 0


def has_ffmpeg():
    try:
        return bool(studio.ffmpeg())
    except studio.StudioError:
        return False


class Text(unittest.TestCase):
    def test_clean(self):
        raw = "## Заголовок\n\nПере-\nнос и **жирный** [текст](http://x.ru).\n\n12\n\nСсылка https://a.b/c тут."
        out = ab.clean(raw)
        self.assertNotIn("#", out)
        self.assertIn("Перенос и жирный текст.", out)
        self.assertNotIn("12", out)
        self.assertNotIn("http", out)

    def test_pieces_respect_size_and_sentences(self):
        text = "Первое предложение. " * 200 + "Очень" + " длинное" * 400 + "."
        parts = ab.pieces(text, 300)
        self.assertTrue(all(len(p) <= 300 for p in parts))
        self.assertTrue(parts[0].endswith("."))
        self.assertEqual(" ".join(parts).split(), text.split())   # ни одно слово не потеряно

    def test_chapters(self):
        text = "Вступление.\n\nГлава 1. Утро\n\nРаз.\n\nГлава 2\n\nДва.\n\nЭпилог\n\nКонец."
        parts = ab.chapters(text)
        self.assertEqual([t for t, _ in parts], ["Начало", "Глава 1. Утро", "Глава 2", "Эпилог"])
        self.assertTrue(parts[1][1].startswith("Глава 1. Утро."))
        self.assertEqual(len(ab.chapters("Просто текст без глав. Глава 1 упоминается в строке.")), 1)

    def test_rate(self):
        self.assertEqual(ab._rate(1.2), "+20%")
        self.assertEqual(ab._rate(0.8), "-20%")
        self.assertEqual(ab._rate("ерунда"), "+0%")
        self.assertEqual(ab._rate(5), "+100%")

    def test_minutes(self):
        self.assertEqual(ab.minutes(9000), 10)


class Books(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)

    def test_fb2(self):
        p = self.dir / "b.fb2"
        p.write_text('<?xml version="1.0"?><FictionBook><body><title><p>Глава 1</p></title><p>Текст &amp; ещё.</p>'
                     '<binary>QUJD</binary></body></FictionBook>', encoding="utf-8")
        text = ab.read_text(p)
        self.assertIn("Текст & ещё.", text)
        self.assertNotIn("QUJD", text)

    def test_epub_in_spine_order(self):
        p = self.dir / "b.epub"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("OEBPS/content.opf", '<package><manifest><item id="a" href="a.xhtml"/><item id="b" href="b.xhtml"/>'
                                            '</manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
            z.writestr("OEBPS/a.xhtml", "<html><body><p>Второе.</p></body></html>")
            z.writestr("OEBPS/b.xhtml", "<html><body><p>Первое.</p></body></html>")
        text = ab.read_text(p)
        self.assertLess(text.index("Первое"), text.index("Второе"))

    def test_txt_and_errors(self):
        p = self.dir / "a.txt"
        p.write_text("Привет.", encoding="utf-8")
        self.assertEqual(ab.read_text(p).strip(), "Привет.")
        with self.assertRaises(ab.AudioError):
            ab.read_text(self.dir / "нет.txt")
        (self.dir / "a.zip").write_bytes(b"x")
        with self.assertRaises(ab.AudioError):
            ab.read_text(self.dir / "a.zip")


class Record(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        p = mock.patch.object(ab, "AUDIO_DIR", self.dir / "out")
        p.start()
        self.addCleanup(p.stop)

    def test_voice_failure_reported_early(self):
        with mock.patch.object(ab, "speak", side_effect=ab.AudioError("голос Microsoft не отвечает")) as speak, \
                mock.patch.object(ab, "_join") as join:
            with self.assertRaises(ab.AudioError) as c:
                ab.record("Раз. " * 1000, "x")
        self.assertEqual(speak.call_count, 1)               # дальше первого куска не пошли
        join.assert_not_called()
        self.assertIn("другим голосом", str(c.exception))

    def test_edge_retries_then_succeeds(self):
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            raise RuntimeError("NoAudioReceived")

        with mock.patch("asyncio.run", side_effect=[RuntimeError("x"), RuntimeError("x"), b"MP3"]):
            self.assertEqual(ab._edge("текст", "ru-RU-SvetlanaNeural", "+0%"), b"MP3")
        with mock.patch("asyncio.run", side_effect=flaky):
            with self.assertRaises(ab.AudioError):
                ab._edge("текст", "ru-RU-DmitryNeural", "+0%")
        self.assertEqual(len(calls), ab.ATTEMPTS)

    def test_chapters_to_files(self):
        joined = {}
        text = "Глава 1\n\n" + "Раз. " * 400 + "\n\nГлава 2\n\nДва."
        with mock.patch.object(ab, "speak", return_value=b"MP3"), \
                mock.patch.object(ab, "_join", side_effect=lambda parts, out: joined.setdefault(out.name, len(parts))):
            files = ab.record(text, "Моя книга")
        self.assertEqual([f.name for f in files], ["01 Глава 1.mp3", "02 Глава 2.mp3"])
        self.assertGreater(joined["01 Глава 1.mp3"], 1)
        self.assertEqual(joined["02 Глава 2.mp3"], 1)
        self.assertIn("моя-книга", files[0].parent.name)

    @unittest.skipUnless(has_ffmpeg(), "нет ffmpeg")
    def test_real_join(self):
        """Настоящая склейка: два кусочка тишины в mp3 → один файл длиной с оба."""
        src = []
        for i in range(2):
            out = self.dir / "s{}.mp3".format(i)
            studio.run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1", "-c:a", "libmp3lame", out])
            src.append(out.read_bytes())
        with mock.patch.object(ab, "speak", side_effect=src):
            files = ab.record("Раз. " * 400, "тишина", progress=lambda d, n: None, split_chapters=False)   # 2000 знаков — два куска
        self.assertAlmostEqual(studio.duration(files[0]), 2.0, delta=0.2)


class Tool(unittest.TestCase):
    def setUp(self):
        media.jobs.clear()
        p = mock.patch.object(studio, "ffmpeg", lambda: "ffmpeg")
        p.start()
        self.addCleanup(p.stop)

    def test_registered_with_permission(self):
        self.assertIn("narrate", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["narrate"], "voice_studio")

    def test_needs_text(self):
        self.assertIn("Нужен text", media.tool_narrate({}))

    def test_short_text_no_question_runs_in_background(self):
        done = threading.Event()
        with mock.patch.object(media, "confirm") as c, \
                mock.patch.object(ab, "record", return_value=[pathlib.Path("/tmp/a.mp3")]) as rec, \
                mock.patch.object(media, "_say", side_effect=lambda t: done.set()) as say:
            out = media.tool_narrate({"text": "Короткий текст.", "voice": "dmitry", "speed": 1.2})
            self.assertIn("Начала озвучку", out)
            self.assertTrue(done.wait(5))
        c.assert_not_called()
        self.assertEqual(rec.call_args[0][2], "ru-RU-DmitryNeural")
        self.assertIn("Озвучка готова", say.call_args[0][0])

    def test_long_or_qwen_asks(self):
        with mock.patch.object(media, "confirm", return_value=False) as c:
            self.assertEqual(media.tool_narrate({"text": "Слово. " * 6000}), "Не озвучиваю.")
            self.assertEqual(media.tool_narrate({"text": "Коротко.", "voice": "qwen"}), "Не озвучиваю.")
        self.assertEqual(c.call_count, 2)
        self.assertIn("кредиты", c.call_args[0][0])

    def test_vault_path_blocked(self):
        with mock.patch.object(permissions, "in_vault", side_effect=lambda p: "secret" in p):
            self.assertEqual(permissions.check("narrate", {"path": "~/secret/book.pdf"})[0], "block")



class EpubChapters(unittest.TestCase):
    def test_headings_become_chapters(self):
        html = ("<html><body><h1>Глава 1</h1><p>Раз. Два.</p><p>Три.</p></body></html>"
                "<html><body><h2>Глава 2</h2><p>Четыре.</p></body></html>")
        text = ab.clean(ab._xml_text(html))
        self.assertEqual([t for t, _ in ab.chapters(text)], ["Глава 1", "Глава 2"])

    def test_heading_glued_to_text_in_txt(self):
        text = ab.clean("Глава 1\nРаз два три.\nГлава 2\nЧетыре пять.")
        self.assertEqual([t for t, _ in ab.chapters(text)], ["Глава 1", "Глава 2"])


if __name__ == "__main__":
    unittest.main()
