"""Creative Studio: ролик из сцен. Рисование и голос подменены; склейка — настоящим ffmpeg, если он есть."""
import pathlib
import tempfile
import threading
import unittest
from unittest import mock

from chloe import qwen_media as qm
from chloe import studio
from chloe.permissions import TOOL_CATEGORY
from chloe.tools import HANDLERS
from chloe.tools import media
from chloe.voice import voice

voice.enabled = False
SCENES = [{"picture": "кошка на окне", "narration": "Вечер."}, {"picture": "город ночью", "narration": ""}]


def has_ffmpeg():
    try:
        return bool(studio.ffmpeg())
    except studio.StudioError:
        return False


class Script(unittest.TestCase):
    def test_clean_scenes(self):
        raw = [{"picture": " кот ", "narration": " Привет. "}, {"narration": "без картинки"}, "мусор",
               {"image": "дом", "text": "Дом."}] + [{"picture": "x"}] * 40
        out = studio.clean_scenes(raw)
        self.assertEqual(out[0], {"picture": "кот", "narration": "Привет."})
        self.assertEqual(out[1], {"picture": "дом", "narration": "Дом."})
        self.assertEqual(len(out), studio.MAX_SCENES)

    def test_estimate(self):
        self.assertAlmostEqual(studio.estimate(SCENES, "slides"), 0.75)          # две сцены и лист героя
        self.assertGreater(studio.estimate(SCENES, "live"), 5)   # живое видео в разы дороже

    def test_no_scenes(self):
        with self.assertRaises(studio.StudioError):
            studio.make_film("x", [{"narration": "нет картинки"}])


class Film(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        p = mock.patch.object(qm, "VIDEO_DIR", self.dir / "vid")
        p.start()
        self.addCleanup(p.stop)

    def picture(self, name="a.png"):
        from PIL import Image

        path = self.dir / name
        Image.new("RGB", (640, 640), (200, 120, 40)).save(path)
        return path

    def test_pipeline_calls(self):
        """Без ffmpeg: каждая сцена рисуется со стилем, клипы склеиваются по порядку."""
        made = []
        (self.dir / "i.png").write_bytes(b"png")

        def clip(img, v, secs, size, out, i=0, ass=None, sfx=None, lead=0.0):
            made.append((i, round(secs, 2), size, bool(ass), bool(sfx)))
            pathlib.Path(out).write_bytes(b"mp4")
            return out

        with mock.patch.object(qm, "image", side_effect=lambda prompt, ratio: [self.dir / "i.png"]) as image, \
                mock.patch.object(studio, "narrate_words", side_effect=lambda text, path: (path, [(0, 1, "слово")], True) if text else (None, [], True)), \
                mock.patch.object(studio, "duration", return_value=4.0), \
                mock.patch.object(studio, "ffmpeg", return_value="ffmpeg"), \
                mock.patch.object(studio, "whoosh", side_effect=lambda path: path), \
                mock.patch.object(studio, "music_track", return_value=None), \
                mock.patch.object(studio, "slide_clip", side_effect=clip), \
                mock.patch.object(studio, "join", side_effect=lambda clips, out: pathlib.Path(out).write_bytes(b"mp4") or out) as join:
            out = studio.make_film("Кошка", SCENES, style="акварель", ratio="9:16")
        # сцена с голосом — субтитры; вторая сцена — со звуком перехода; у последней — свои секунды финала
        end = round(3.0 + studio.ending_hold(studio.clean_scenes(SCENES)), 2)
        self.assertEqual(sorted(made), [(0, 4.5, (1080, 1920), True, False), (1, end, (1080, 1920), False, True)])
        self.assertEqual({c[0][0] for c in image.call_args_list}, {"кошка на окне. акварель", "город ночью. акварель"})
        self.assertEqual([c.name for c in join.call_args[0][0]], ["clip00.mp4", "clip01.mp4"])
        self.assertEqual(out.parent, self.dir / "vid")

    def test_drawing_error_becomes_studio_error(self):
        with mock.patch.object(qm, "image", side_effect=qm.MediaError("кредиты Qwen закончились")), \
                mock.patch.object(studio, "ffmpeg", return_value="ffmpeg"):
            with self.assertRaises(studio.StudioError) as c:
                studio.make_film("x", SCENES)
        self.assertIn("кредиты", str(c.exception))

    @unittest.skipUnless(has_ffmpeg(), "нет ffmpeg")
    def test_real_ffmpeg_film(self):
        img = self.picture()
        with mock.patch.object(qm, "image", return_value=[img]), mock.patch.object(studio, "narrate_words", return_value=(None, [], True)), \
                mock.patch.object(studio, "MIN_SCENE", 1.0), mock.patch.object(studio, "music_track", return_value=None):
            out = studio.make_film("Проба", SCENES, ratio="1:1")
        self.assertTrue(out.is_file())
        self.assertAlmostEqual(studio.duration(out), 2.0 + studio.ending_hold(studio.clean_scenes(SCENES)), delta=0.3)


class Tool(unittest.TestCase):
    def setUp(self):
        media.jobs.clear()
        for target, name, val in ((qm.config, "QWEN_KEY", "sk-sp-test"), (studio, "ffmpeg", lambda: "ffmpeg")):
            p = mock.patch.object(target, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_registered_with_permission(self):
        self.assertIn("make_film", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["make_film"], "media")

    def test_needs_script(self):
        self.assertIn("Нужен сценарий", media.tool_make_film({"title": "x"}))

    def test_confirmation_names_cost_and_scenes(self):
        with mock.patch.object(media, "confirm", return_value=False) as c, mock.patch.object(studio, "make_film") as film:
            self.assertEqual(media.tool_make_film({"title": "Кошка", "scenes": SCENES}), "Не делаю ролик.")
        film.assert_not_called()
        q = c.call_args[0][0]
        self.assertIn("«Кошка» из 2 сцен", q)
        self.assertIn("% месячного пакета", q)
        self.assertIn("Вечер.", q)

    def test_runs_in_background_and_announces(self):
        done = threading.Event()
        with mock.patch.object(media, "confirm", return_value=True), mock.patch.object(media, "show") as show, \
                mock.patch.object(studio, "make_film", return_value=pathlib.Path("/tmp/film.mp4")), \
                mock.patch.object(media, "_say", side_effect=lambda t: done.set()) as say:
            out = media.tool_make_film({"title": "Кошка", "scenes": SCENES, "mode": "live"})
            self.assertIn("Начала ролик", out)
            self.assertTrue(done.wait(5))
        self.assertIn("Ролик готов", say.call_args[0][0])
        show.assert_called_once()
        self.assertIn("ролик «Кошка» — готово", media.tool_create_media({"action": "status"}))


if __name__ == "__main__":
    unittest.main()
