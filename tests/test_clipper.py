"""Нарезчик клипов из игр и стримов: оценка моментов, выбор отрезков, веб-камера, субтитры, сборка клипа, инструмент.
Распознавание речи и детектор лиц здесь не запускаются — данные искусственные."""
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from chloe import clipper as C
from chloe import studio


class Moments(unittest.TestCase):
    def test_hot_words_and_laughter_count_more(self):
        words = [{"s": 10.0, "e": 10.4, "w": "Офигеть!"}, {"s": 10.5, "e": 10.8, "w": "ахахах"},
                 {"s": 40.0, "e": 40.3, "w": "ну"}, {"s": 40.4, "e": 40.6, "w": "ладно"}]
        sp = C.speech_curve(words, int(60 / C.HOP))
        self.assertGreater(sp[int(10.3 / C.HOP)], sp[int(40.3 / C.HOP)] * 3)

    def test_explosion_beats_steady_noise(self):
        n = int(120 / C.HOP)
        audio = np.full(n, 0.1)
        audio[int(70 / C.HOP):int(71 / C.HOP)] = 0.9                    # взрыв на 70-й секунде
        sc = C.score_curve(audio, np.zeros(n), np.zeros(n))
        self.assertAlmostEqual(np.argmax(sc) * C.HOP, 70.5, delta=1.0)

    def test_moments_have_buildup_do_not_overlap_and_keep_phrases(self):
        n = int(300 / C.HOP)
        sc = np.zeros(n)
        for t, v in ((60, 1.0), (62, 0.9), (200, 0.8), (290, 0.7)):
            sc[int(t / C.HOP)] = v
        words = [{"s": 48.6, "e": 49.4, "w": "смотри"}]                 # граница клипа попала бы в слово
        ms = C.pick_moments(sc, words, 300, count=3, length=30)
        self.assertEqual(len(ms), 3)
        for a, b, peak, _s in ms:
            self.assertTrue(C.LENGTH[0] * 0.8 <= b - a <= C.LENGTH[1] + 1)
            self.assertTrue(a < peak < b)
            self.assertGreaterEqual(peak - a, 5)                         # есть разгон до пика
            self.assertFalse(any(w["s"] < a < w["e"] or w["s"] < b < w["e"] for w in words))
        spans = sorted((a, b) for a, b, _p, _s in ms)
        self.assertTrue(all(x[1] <= y[0] for x, y in zip(spans, spans[1:])))
        self.assertEqual(ms[0][2], 60.0)                                 # лучший — первым

    def test_music_without_talk_is_flagged(self):
        audio = np.full(600, 0.2)
        self.assertTrue(C.music_suspect(audio, [], 0, 60))
        words = [{"s": i * 0.5, "e": i * 0.5 + 0.3, "w": "да"} for i in range(120)]
        self.assertFalse(C.music_suspect(audio, words, 0, 60))           # стример говорит — не музыка


class Facecam(unittest.TestCase):
    def test_stationary_face_is_the_webcam(self):
        frames = []
        for k in range(10):
            fr = [(0.85 + 0.005 * (k % 3), 0.72, 0.03, 0.05)]              # лицо стримера: всегда в правом нижнем углу
            fr.append((0.1 + 0.08 * k, 0.4, 0.02, 0.03))                   # герой игры бегает по экрану
            frames.append(fr)
        x, y, w, h = C.facecam_rect(frames)
        self.assertTrue(x + w / 2 > 0.75 and y + h / 2 > 0.6)
        self.assertLessEqual(x + w, 1.0001)
        self.assertLessEqual(y + h, 1.0001)

    def test_no_steady_face_means_no_webcam(self):
        frames = [[(0.1 + 0.08 * k, 0.4, 0.02, 0.03)] for k in range(10)]
        self.assertIsNone(C.facecam_rect(frames))
        self.assertIsNone(C.facecam_rect([[] for _ in range(10)]))

    def test_game_crop_avoids_the_webcam(self):
        right = (0.78, 0.6, 0.22, 0.3)
        x = C.game_x(right, 1920, 1190)
        self.assertLessEqual(x + 1190, 0.78 * 1920 + 1)
        left = (0.0, 0.6, 0.22, 0.3)
        self.assertGreaterEqual(C.game_x(left, 1920, 1190), 0.22 * 1920 - 1)


class Captions(unittest.TestCase):
    def test_groups(self):
        words = [{"s": i * 0.3, "e": i * 0.3 + 0.25, "w": w} for i, w in enumerate("раз два три четыре пять".split())]
        words.append({"s": 5.0, "e": 5.3, "w": "потом"})                   # пауза — новая группа
        g = C.caption_groups(words, 0, 10)
        self.assertEqual([len(x[2]) for x in g], [3, 2, 1])
        self.assertEqual(C.caption_groups(words, 4.0, 10)[0][2][0]["w"], "потом")

    def test_meta_from_model_and_fallback(self):
        reply = json.dumps({"clips": [{"hook": "Он не ожидал взрыва", "title": "Взрыв на мосту"}]})
        m = C.clip_meta(["вот это взрыв офигеть"], "GTA 6", ask=lambda p, think=False: reply)
        self.assertEqual(m[0]["hook"], "Он не ожидал взрыва")

        def broken(p, think=False):
            raise RuntimeError("нет модели")
        fb = C.clip_meta(["вот это взрыв офигеть ну и ну"], ask=broken)
        self.assertEqual(fb[0]["hook"], "вот это взрыв офигеть ну")


class Render(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.video = self.dir / "game.mp4"
        subprocess.run([studio.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3",
                        "-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", str(self.video)], check=True)

    def test_vertical_clip_both_layouts(self):
        info = C.probe(self.video)
        self.assertEqual((info["w"], info["h"]), (640, 360))
        words = [{"s": 0.5, "e": 0.9, "w": "вау"}, {"s": 1.0, "e": 1.4, "w": "погнали!"}]
        for layout, cam in (("game", None), ("streamer", (0.75, 0.6, 0.25, 0.3))):
            out = self.dir / ("c-" + layout + ".mp4")
            C.render_clip(self.video, out, 0.5, 2.5, 1.5, layout, cam, words, "Смотри до конца", info)
            self.assertEqual(C.probe(out)["w"], 1080)
            self.assertAlmostEqual(studio.duration(out), 2.0, delta=0.2)

    def test_whole_pipeline_without_speech_model(self):
        with mock.patch.object(C, "transcribe", return_value=[]), mock.patch.object(C, "find_facecam", return_value=None), \
                mock.patch.object(C, "LENGTH", (1.0, 2.0)):
            made = C.clip(self.video, self.dir / "out", count=1, length=2, game="GTA 6", ask=False, progress=lambda t: None,
                          vision=False)
        self.assertEqual(len(made), 1)
        notes = (self.dir / "out" / "clips.txt").read_text(encoding="utf-8")
        self.assertIn("#GTA6", notes)
        self.assertIn("Content ID", notes)


class Teaser(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        # 6 с: первые 4 — чёрные, потом 2 — белые (это «пик»); звук весь ролик
        self.clip = self.dir / "clip.mp4"
        subprocess.run([studio.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x568:r=30:d=4",
                        "-f", "lavfi", "-i", "color=c=white:s=320x568:r=30:d=2", "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a", "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(self.clip)], check=True)

    def brightness(self, t):
        raw = subprocess.run([studio.ffmpeg(), "-v", "error", "-ss", str(t), "-i", str(self.clip), "-frames:v", "1",
                              "-vf", "scale=8:8", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
        return sum(raw) / max(1, len(raw))

    def test_peak_first_then_story_from_start(self):
        self.assertTrue(C.add_teaser(self.clip, 4.6))
        self.assertAlmostEqual(studio.duration(self.clip), 6 + C.TEASER, delta=0.15)
        self.assertGreater(self.brightness(0.6), 200)          # первые 1,2 с — пик (белое)
        self.assertLess(self.brightness(2.0), 40)              # потом — начало клипа (чёрное)
        self.assertTrue(C.probe(self.clip)["audio"])

    def test_broken_file_stays_as_is(self):
        bad = self.dir / "bad.mp4"
        bad.write_bytes(b"not a video")
        self.assertFalse(C.add_teaser(bad, 4.0))
        self.assertEqual(bad.read_bytes(), b"not a video")

    def test_pipeline_skips_teaser_when_peak_is_at_start(self):
        calls = []
        with mock.patch.object(C, "render_clip"), mock.patch.object(C, "add_teaser", side_effect=lambda *a: calls.append(a)), \
                mock.patch.object(C, "probe", return_value={"secs": 60, "w": 640, "h": 360, "fps": 30, "audio": True}), \
                mock.patch.object(C, "audio_curve", return_value=C.np.zeros(600)), \
                mock.patch.object(C, "motion_curve", return_value=(C.np.zeros(600), [])), \
                mock.patch.object(C, "onset_curve", return_value=None), mock.patch.object(C, "transcribe", return_value=[]), \
                mock.patch.object(C, "find_facecam", return_value=None), \
                mock.patch.object(C, "choose_moments", return_value=([(10.0, 40.0, 21.0, 0.9), (50.0, 60.0, 51.0, 0.5)],
                                                                    [{"hook": "h", "title": "t"}] * 2)):
            C.clip(self.dir / "rec.mp4", self.dir / "out", count=2, ask=False, progress=lambda t: None, vision=False)
        self.assertEqual([round(c[1]) for c in calls], [11])                  # пик на 11-й секунде — тизер; на 1-й — нет


class Tool(unittest.TestCase):
    def test_needs_a_video(self):
        from chloe.tools import media

        self.assertIn("Нужна запись", media.tool_clip_video({"path": "/нет/такого.mp4"}))


if __name__ == "__main__":
    unittest.main()


class Selection(unittest.TestCase):
    """ИИ-отбор моментов (модель подменена), перевод, стили."""

    def test_candidates_cover_the_whole_recording(self):
        sc = np.zeros(int(600 / C.HOP))
        sc[int(100 / C.HOP)] = 1.0
        cands = C.candidates(sc, [], 600, n=12, length=30)
        self.assertGreaterEqual(len(cands), 10)
        self.assertLess(min(a for a, _b, _p, _s in cands), 60)          # и начало записи
        self.assertGreater(max(b for _a, b, _p, _s in cands), 540)      # и конец — ИИ видит тихие сценки
        spans = sorted((a, b) for a, b, _p, _s in cands)
        self.assertTrue(all(x[1] <= y[0] for x, y in zip(spans, spans[1:])))

    def test_ai_picks_fight_and_joke_not_riding(self):
        cands = [(0, 30, 15, 0.9), (30, 60, 45, 0.8), (60, 90, 75, 0.1), (90, 120, 105, 0.1)]
        reply = json.dumps({"style": "fantasy", "clips": [
            {"i": 1, "score": 2, "kind": "пейзаж", "why": "езда", "hook": "Едем", "title": "Езда"},
            {"i": 2, "score": 1, "kind": "скучно", "why": "карта", "hook": "Карта", "title": "Карта"},
            {"i": 3, "score": 8, "kind": "бой", "why": "бой с утопцами", "hook": "Утопцы атакуют!", "title": "Бой"},
            {"i": 4, "score": 7, "kind": "смешно", "why": "шутка", "hook": "Он так и сказал", "title": "Смешно"}]})
        seen = {}

        def vision(prompt, images):
            seen["prompt"], seen["images"] = prompt, images
            return reply
        with mock.patch.object(C, "frames_jpeg", return_value=[b"jpg"] * 3), mock.patch.object(C, "candidates", return_value=cands):
            moments, meta = C.choose_moments("v.mp4", np.zeros(1200), [], 120, 2, 30, "The Witcher 3", vision)
        self.assertEqual([m[0] for m in moments], [60, 90])               # бой и смешное, не езда и не карта
        self.assertEqual(meta[0]["hook"], "Утопцы атакуют!")
        self.assertEqual(C.judge.style, "fantasy")
        self.assertEqual(len(seen["images"]), 12)                          # по 3 кадра на кандидата
        self.assertIn("смешное", seen["prompt"])

    def test_without_ai_signals_decide(self):
        def broken(prompt, images):
            raise RuntimeError("нет ключа")
        sc = np.zeros(1200)
        sc[700] = 1.0
        with mock.patch.object(C, "frames_jpeg", return_value=[b"jpg"]):
            moments, meta = C.choose_moments("v.mp4", sc, [], 120, 1, 30, vision=broken)
        self.assertIsNone(meta)
        self.assertTrue(moments[0][0] < 70 < moments[0][1])

    def test_foreign_speech_is_translated_by_sentences(self):
        words = [{"s": 1.0, "e": 1.3, "w": "Don't"}, {"s": 1.3, "e": 1.6, "w": "laugh."},
                 {"s": 3.0, "e": 3.4, "w": "Thanks,"}, {"s": 3.4, "e": 3.9, "w": "Dijkstra."}]
        self.assertTrue(C.foreign(words * 6, 0, 10))
        self.assertFalse(C.foreign([{"s": 1, "e": 2, "w": "Привет, как дела у тебя сегодня утром"}], 0, 10))
        reply = json.dumps({"lines": ["Не смейся.", "Спасибо, Дийкстра."]})
        out = C.translate_words(words, 0, 10, ask=lambda p, think=False: reply)
        self.assertEqual(" ".join(w["w"] for w in out), "Не смейся. Спасибо, Дийкстра.")
        self.assertTrue(all(1.0 <= w["s"] < 1.6 for w in out[:2]))          # перевод — во время своей фразы
        bad = C.translate_words(words, 0, 10, ask=lambda p, think=False: json.dumps({"lines": ["одна строка"]}))
        self.assertEqual(bad, words)                                       # список не той длины — как было
        part = C.translate_words(words, 0, 10, ask=lambda p, think=False: json.dumps({"lines": {"2": "Спасибо, Дийкстра."}}))
        self.assertEqual(" ".join(w["w"] for w in part), "Don't laugh. Спасибо, Дийкстра.")   # нет одной — только она как была

    def test_styles_by_game(self):
        self.assertEqual(C.style_for("The Witcher 3"), "fantasy")
        self.assertEqual(C.style_for("Ведьмак 3"), "fantasy")
        self.assertEqual(C.style_for("GTA 6"), "vice")
        self.assertEqual(C.style_for("Cyberpunk 2077"), "cyber")
        self.assertEqual(C.style_for("Call of Duty"), "military")
        self.assertIsNone(C.style_for("Tetris"))
        for st in C.STYLES.values():
            for key in ("caption", "hook", "fill", "stroke", "accent", "hook_color", "size"):
                self.assertIn(key, st)

    def test_every_style_draws(self):
        import cairo

        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 1080, 1920)
        c = cairo.Context(surf)
        group = (0, 1, [{"s": 0, "e": 0.5, "w": "Утопцы"}, {"s": 0.5, "e": 1, "w": "лезут!"}])
        for st in C.STYLES:
            C.draw_hook(c, "Он не ожидал взрыва", 200, st)
            C.draw_caption(c, group, 0.6, 1300, st)
