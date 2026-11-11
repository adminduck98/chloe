"""Стикмен-режиссёр: стили и паспорт героя, ритм, субтитры по словам, раскадровка, пробный кусок и продолжение."""
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from chloe import qwen_media as qm
from chloe import screenplay as sp
from chloe import stickman_styles as ST
from chloe import studio
from chloe.tools import media


def script(n=6, key="classic_dark"):
    return {"title": "Почему стикмен не устаёт", "logline": "x", "style_key": key, "characters": "",
            "scenes": [{"stage": "hook", "picture": "the hero jumps over a laptop, wide shot", "video": "[0-3s] jumps",
                        "beats": ["прыгает", "падает", "встаёт"], "narration": "Фраза номер {} про стикмена.".format(i)}
                       for i in range(n)]}


class Styles(unittest.TestCase):
    def test_find_by_key_or_words(self):
        self.assertEqual(ST.find("classic_dark"), "classic_dark")
        self.assertEqual(ST.find("сделай в тёмном стиле"), "classic_dark")
        self.assertEqual(ST.find("как пещерные люди, древние"), "prehistoric")
        self.assertIsNone(ST.find("акварель"))

    def test_passport_is_in_every_frame_verbatim(self):
        frames = sp.frames(script())
        anchor = ST.STYLES["classic_dark"]["anchor"]
        self.assertTrue(all(anchor in f["picture"] and anchor in f["video"] for f in frames))
        self.assertTrue(all("No text" in f["picture"] for f in frames))

    def test_own_cast_replaces_default_passport(self):
        s = dict(script(), characters="Bolt: a red stick figure; Byte: a blue stick figure")
        self.assertIn("Bolt: a red stick figure", sp.frames(s)[0]["picture"])

    def test_pacing(self):
        n, sec, words = sp.pacing(60)
        self.assertEqual((n, sec), (8, 8))
        self.assertEqual(sp.pacing(10)[0], 4)                      # короче — всё равно четыре сцены
        self.assertLessEqual(sp.pacing(10 ** 6)[0], studio.MAX_SCENES)

    def test_prompt_has_arc_and_catalog(self):
        p = sp.prompt("видео про стикмена", duration=60)
        self.assertIn("Золотой крючок", p)
        self.assertIn("classic_light", p)
        self.assertIn("Сцен — ровно 8", p)
        self.assertNotIn("classic_light", sp.prompt("x", duration=60, style_key="cozy").split("СТИЛЬ")[1].split("Ответь")[0])

    def test_parse_keeps_storyboard_fields(self):
        out = sp.parse(json.dumps(script(), ensure_ascii=False))
        self.assertEqual(out["style_key"], "classic_dark")
        self.assertEqual(out["scenes"][0]["beats"], ["прыгает", "падает", "встаёт"])
        self.assertEqual(out["scenes"][0]["stage"], "hook")


class Captions(unittest.TestCase):
    def test_punctuation_comes_back(self):
        w = studio.with_punctuation([(0, 1, "Почему"), (1, 2, "устаёт"), (2, 3, "Ответ")], "Почему устаёт? Ответ.")
        self.assertEqual([x[2] for x in w], ["Почему", "устаёт?", "Ответ."])

    def test_phrases_break_on_sense_and_do_not_overlap(self):
        ph = studio.phrases([(0, .3, "Стикмен"), (.3, .6, "прыгнул,"), (2, 2.3, "чем"), (2.3, 2.6, "мог.")])
        self.assertEqual([p[2] for p in ph], ["Стикмен прыгнул,", "чем мог."])
        self.assertLessEqual(ph[0][1], ph[1][0])

    def test_ass_file(self):
        d = pathlib.Path(tempfile.mkdtemp())
        studio.captions_ass([(0, 1, "Привет,"), (1, 2, "{мир}")], (1280, 720), d / "c.ass", shift=0.3)
        text = (d / "c.ass").read_text(encoding="utf-8")
        self.assertIn("PlayResX: 1280", text)
        self.assertIn("0:00:00.30", text)                          # сдвиг на звук перехода
        self.assertNotIn("{мир}", text)                            # фигурные скобки — команды ASS, их нельзя пропускать

    def test_even_words_when_no_timing(self):
        w = studio.even_words("раз два три", 3.0)
        self.assertEqual(len(w), 3)
        self.assertAlmostEqual(w[-1][1], 3.0, delta=0.01)

    def test_preview_is_about_twenty_seconds(self):
        scenes = [{"picture": "x", "narration": "а" * 100}] * 8    # ~7,6 с на сцену
        self.assertEqual(studio.preview_count(scenes), 3)
        self.assertEqual(studio.preview_count(scenes[:2]), 2)


class Tool(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for target, name, val in ((qm, "VIDEO_DIR", self.dir / "vid"), (studio, "PROJECTS", self.dir / "vid" / "проекты"),
                                  (qm.config, "QWEN_KEY", "sk-sp-test"), (studio, "ffmpeg", lambda: "ffmpeg"),
                                  (media, "_say", lambda t: None), (media, "show", lambda p: None)):
            p = mock.patch.object(target, name, val)
            p.start()
            self.addCleanup(p.stop)
        media.jobs.clear()

    def test_director_mode_writes_storyboard_without_paying(self):
        with mock.patch.object(sp, "write", return_value=sp.parse(json.dumps(script(), ensure_ascii=False))), \
                mock.patch.object(media, "confirm") as ask, mock.patch.object(qm, "image") as image:
            out = media.tool_make_film({"idea": "стикмен", "mode": "director"})
        ask.assert_not_called()
        image.assert_not_called()
        self.assertIn("кредиты не тратились", out)
        md = next((self.dir / "vid" / "раскадровки").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("Сцена 1", md)
        self.assertIn(ST.STYLES["classic_dark"]["anchor"], md)
        self.assertIn("крючок", md)

    def test_long_film_starts_with_preview(self):
        long = script(8)
        for sc in long["scenes"]:
            sc["narration"] = "а" * 100
        with mock.patch.object(sp, "write", return_value=long), mock.patch.object(media, "confirm", return_value=True) as ask, \
                mock.patch.object(studio, "make_film", return_value=self.dir / "p.mp4") as film:
            out = media.tool_make_film({"idea": "стикмен"})
            for _ in range(50):
                if media.jobs and list(media.jobs.values())[0]["state"] != "работаю":
                    break
                import time
                time.sleep(0.05)
        self.assertIn("пробный кусок", out.lower())
        self.assertIn("Сначала пробный кусок — 3 сцены", ask.call_args[0][0])
        self.assertEqual(film.call_args.kwargs["upto"], 3)
        project = film.call_args.kwargs["project"]
        self.assertTrue((project / "project.json").exists())

    def test_continue_renders_the_rest(self):
        folder = studio.new_project("Ролик", script(8)["scenes"], "", "16:9", "slides")
        for i in range(3):
            (folder / "clip{:02d}.mp4".format(i)).write_bytes(b"x")
        with mock.patch.object(media, "confirm", return_value=True) as ask, \
                mock.patch.object(studio, "make_film", return_value=self.dir / "f.mp4") as film:
            out = media.tool_make_film({"action": "continue"})
        self.assertIn("ещё 5 сцен из 8", ask.call_args[0][0])
        self.assertEqual(film.call_args.kwargs["upto"], 8)
        self.assertIn("Начала ролик", out)

    def test_continue_without_projects(self):
        self.assertIn("нет начатых роликов", media.tool_make_film({"action": "continue"}))


class Craft(unittest.TestCase):
    """Приёмы cinecode: поворот, тип и план сцены, крючок в движении, «вжух» не на каждом стыке, секунды финала, громкость."""

    def good(self):
        beats, shots = ["start", "change", "quiet", "turn", "connection", "ending"], ["wide", "medium", "close", "wide", "medium", "close"]
        s = script(6)
        s["turn"] = "до: прячется / после: спорит"
        for sc, b, sh in zip(s["scenes"], beats, shots):
            sc.update(beat=b, shot=sh)
        return s

    def test_check_words(self):
        self.assertEqual(sp.check_words(self.good()), [])
        s = self.good()
        s["turn"] = ""
        s["scenes"][0]["narration"] = "Представьте мир! Ура! Да! Вот!"
        for sc in s["scenes"][:3]:
            sc["beat"] = "change"
        s["scenes"][4]["shot"] = s["scenes"][3]["shot"]
        found = " | ".join(sp.check_words(s))
        for part in ("представьте", "восклицательных", "три подряд", "одинаковый план", "нет поворота"):
            self.assertIn(part, found)

    def test_prompt_and_parse_keep_turn_beat_shot(self):
        p = sp.prompt("видео про стикмена", duration=60)
        self.assertIn("ТИП СЦЕНЫ", p)
        self.assertIn("Штампы запрещены", p)
        out = sp.parse(json.dumps(self.good(), ensure_ascii=False))
        self.assertEqual(out["turn"], "до: прячется / после: спорит")
        self.assertEqual((out["scenes"][3]["beat"], out["scenes"][3]["shot"]), ("turn", "wide"))

    def test_editor_gets_found_problems(self):
        bad = dict(self.good(), turn="")
        asked = []

        def ask(text, think=True):
            asked.append(text)
            return json.dumps(self.good(), ensure_ascii=False)

        with mock.patch.object(sp, "call", side_effect=lambda a, text, think: ask(text) if asked else (asked.append(text) or json.dumps(bad, ensure_ascii=False))), \
                mock.patch.object(sp, "research", return_value=""), mock.patch.object(sp, "fit_length", side_effect=lambda s, d, a: s):
            sp.write("стикмен", duration=48)
        self.assertIn("НАЙДЕНО ПРОВЕРКОЙ", asked[1])
        self.assertIn("нет поворота", asked[1])

    def test_hook_moves_from_the_first_frame(self):
        anim = {"actors": [{"id": "hero", "x": 0.3}], "acting": [{"who": "hero", "do": "talk", "from": 0, "to": 1}]}
        sp.hook_motion(anim)
        self.assertEqual(anim["acting"][0]["do"], "walk")
        self.assertEqual(anim["acting"][1]["from"], 0.18)
        busy = {"actors": [{"id": "hero"}], "acting": [{"who": "hero", "do": "run", "from": 0, "to": 1, "x": 0.8}]}
        self.assertEqual(len(sp.hook_motion(busy)["acting"]), 1)
        s = sp.fill_anim(script(3))
        self.assertIn(s["scenes"][0]["anim"]["acting"][0]["do"], sp.ACTIVE)

    def test_whoosh_only_on_some_cuts(self):
        scenes = [{"narration": "а" * 80, "stage": st, "beat": b} for st, b in
                  (("hook", "start"), ("myth", "change"), ("myth", "travel"), ("secret", "build"), ("secret", "quiet"),
                   ("truth", "turn"), ("truth", "build"), ("finale", "ending"))]
        plan = studio.transition_plan(scenes)
        self.assertTrue(plan)
        self.assertFalse(any(i - 1 in plan for i in plan))              # никогда два стыка подряд
        self.assertNotIn(4, plan)                                         # перед тихой сценой — тишина
        self.assertNotIn(0, plan)
        self.assertEqual(studio.transition_plan([{"narration": "x"}] * 5), {1, 3})   # без пометок — через стык
        many = [{"narration": "а" * 10, "beat": "change"} for _ in range(12)]          # короткие сцены по ~3 с
        starts = [sum(studio.scene_seconds(sc) for sc in many[:i]) for i in range(len(many))]
        plan = sorted(studio.transition_plan(many))
        self.assertTrue(all(sum(1 for j in plan if 0 <= starts[i] - starts[j] < 30) <= 2 for i in plan))   # не больше двух за 30 с

    def test_ending_keeps_its_seconds(self):
        self.assertAlmostEqual(studio.ending_hold([{"narration": "а" * 100}] * 3) + studio.TAIL, 2.0)
        self.assertAlmostEqual(studio.ending_hold([{"narration": "а" * 100}] * 20) + studio.TAIL, 4.0)

    def test_shot_sets_the_camera_and_it_drifts(self):
        from chloe import animator as A

        def zoom(shot, beat="build", t=0.0):
            spec = {"actors": [{"id": "a", "x": 0.3}], "acting": [], "shot": shot, "beat": beat}
            return A.Scene(spec, "classic_light", (320, 180), 4.0).cam(t)[0]

        self.assertLess(zoom("wide"), zoom("medium"))
        self.assertLess(zoom("medium"), zoom("close"))
        self.assertGreater(zoom("medium", t=3.9), zoom("medium", t=0.0))   # камера плывёт до самого стыка
        self.assertEqual(zoom("close", "quiet", 3.9), zoom("close", "quiet", 0.0))
        self.assertEqual(A.Scene({"actors": [{"id": "a"}]}, "classic_light", (320, 180), 4.0).cam(2.0)[0], 1.0)


def has_ffmpeg():
    try:
        studio.ffmpeg()
        return True
    except studio.StudioError:
        return False


class RealFilm(unittest.TestCase):
    @unittest.skipUnless(has_ffmpeg(), "нет ffmpeg")
    def test_master_brings_loudness_to_target(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        src = d / "quiet.mp4"
        studio.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=64x64:d=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                           "-af", "volume=0.05", "-shortest"] + studio.VIDEO_OUT + studio.AUDIO_OUT + [src])
        out = studio.master(src, d / "loud.mp4")
        err = studio.run_ffmpeg(["-i", out, "-af", "ebur128", "-f", "null", "-"])
        loud = float([ln for ln in err.splitlines() if ln.strip().startswith("I:")][-1].split()[1])
        self.assertAlmostEqual(loud, studio.LOUDNESS, delta=1.0)

    @unittest.skipUnless(has_ffmpeg(), "нет ffmpeg")
    def test_captions_and_whoosh_render(self):
        from PIL import Image

        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        img = d / "a.png"
        Image.new("RGB", (64, 64), "white").save(img)
        voice = d / "v.wav"
        studio.run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:duration=1.2", voice])
        words = [(0.0, 0.5, "Привет,"), (0.5, 1.1, "стикмен!")]

        def fake_words(text, path):
            shutil.copyfile(voice, path)
            return path, words, True

        scenes = [{"picture": "x", "narration": "Привет, стикмен!"}, {"picture": "y", "narration": "Привет, стикмен!"}]
        with mock.patch.object(qm, "image", return_value=[img]), mock.patch.object(studio, "narrate_words", side_effect=fake_words), \
                mock.patch.object(qm, "VIDEO_DIR", d / "out"), mock.patch.object(studio, "music_track", return_value=None), \
                mock.patch.object(studio, "MIN_SCENE", 1.0):
            out = studio.make_film("Проба", scenes, ratio="1:1", project=d / "proj", workers=1)
        self.assertTrue(out.is_file())
        self.assertTrue((d / "proj" / "captions00.ass").exists())
        self.assertTrue((d / "proj" / "whoosh.wav").exists())      # звук перехода — со второй сцены
        # вторая сцена длиннее первой на вступление после «вжуха» и на секунды финала
        self.assertAlmostEqual(studio.duration(d / "proj" / "clip01.mp4") - studio.duration(d / "proj" / "clip00.mp4"),
                               studio.LEAD + studio.ending_hold(scenes), delta=0.15)
        self.assertTrue((d / "proj" / "проверка-звука.json").exists())     # Хлоя послушала готовый ролик


if __name__ == "__main__":
    unittest.main()
