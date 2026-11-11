"""Сценарист: идея → поиск → сценарий → редактор; сбой поиска или редактора не ломает ролик."""
import json
import unittest
from unittest import mock

from chloe import screenplay as sp
from chloe import studio
from chloe.tools import media


def script(tag, n=6):
    return json.dumps({"title": "Ролик " + tag, "logline": "Синий стикмен хочет выйти из файла, но Курсор мешает",
                       "style": "чёрный фон, неон", "characters": "Синий — маленький синий стикмен с белыми глазами",
                       "scenes": [{"picture": "Синий — маленький синий стикмен, кадр %d" % i, "narration": "Фраза %d %s" % (i, tag)}
                                  for i in range(n)]}, ensure_ascii=False)


class Write(unittest.TestCase):
    def test_idea_goes_through_search_writer_and_editor(self):
        prompts = []

        def ask(p):
            prompts.append(p)
            return script("черновик" if len(prompts) == 1 else "правка")

        out = sp.write("видео про стикмена", "как у Animator vs Animation", ask=ask, search=lambda a: "Найдено: приёмы " + a["query"])
        self.assertEqual(len(prompts), 2)
        self.assertIn("видео про стикмена", prompts[0])
        self.assertIn("как у Animator vs Animation", prompts[0])          # подсказка пользователя
        self.assertIn("Найдено: приёмы", prompts[0])                        # материалы из интернета
        self.assertIn("СЦЕНАРИЙ", prompts[1])                               # второй проход — редактор
        self.assertIn("правка", out["scenes"][0]["narration"])

    def test_search_failure_does_not_stop_the_script(self):
        def broken(a):
            raise RuntimeError("поисковики не отвечают")

        out = sp.write("ролик про кота", ask=lambda p: script("ок"), search=broken, refine=False)
        self.assertEqual(len(out["scenes"]), 6)

    def test_editor_failure_keeps_first_draft(self):
        calls = []

        def ask(p):
            calls.append(p)
            if len(calls) == 2:
                raise RuntimeError("нет связи")
            return script("первый")

        out = sp.write("ролик", ask=ask, search=lambda a: "")
        self.assertIn("первый", out["scenes"][0]["narration"])

    def test_too_short_script_is_rejected(self):
        with self.assertRaises(sp.ScriptError):
            sp.parse(script("x", n=2))

    def test_json_inside_chatter(self):
        self.assertEqual(len(sp.parse("Вот сценарий:\n" + script("x") + "\nУдачи!")["scenes"]), 6)

    def test_style_line_repeats_hero_passport(self):
        line = sp.style_line(sp.parse(script("x")))
        self.assertIn("чёрный фон", line)
        self.assertIn("маленький синий стикмен", line)

    def test_no_idea(self):
        with self.assertRaises(sp.ScriptError):
            sp.write(" ", ask=lambda p: "")


class Tool(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(media.qm, "available", return_value=True),
                  mock.patch.object(studio, "ffmpeg", return_value="ffmpeg"), mock.patch.object(media, "_say")):
            p.start()
            self.addCleanup(p.stop)

    def test_idea_makes_script_and_asks_before_paying(self):
        with mock.patch.object(sp, "write", return_value=sp.parse(script("т"))) as w, \
                mock.patch.object(media, "confirm", return_value=False) as ask:
            out = media.tool_make_film({"idea": "видео про стикмена", "notes": "смотри на YouTube"})
        w.assert_called_once_with("видео про стикмена", "смотри на YouTube", 60, style_key=None, anim=False)
        self.assertEqual(out, "Не делаю ролик.")
        question = ask.call_args[0][0]
        self.assertIn("Ролик т", question)                                  # название от сценариста
        self.assertIn("Фраза 0 т", question)                                # сценарий виден до оплаты

    def test_script_failure_is_reported(self):
        with mock.patch.object(sp, "write", side_effect=sp.ScriptError("нет ключа")):
            self.assertIn("Не смогла написать сценарий", media.tool_make_film({"idea": "ролик"}))

    def test_nothing_given(self):
        self.assertIn("idea", media.tool_make_film({}))

    def test_ready_scenes_skip_the_writer(self):
        with mock.patch.object(sp, "write") as w, mock.patch.object(media, "confirm", return_value=False):
            media.tool_make_film({"scenes": [{"picture": "кадр", "narration": "слово"}]})
        w.assert_not_called()


if __name__ == "__main__":
    unittest.main()
