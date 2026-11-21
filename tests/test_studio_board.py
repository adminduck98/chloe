"""Студия: доска серий по папкам проектов, идеи, действия только над своими проектами."""
import json
import shutil
import time
import unittest
from unittest import mock

from chloe import remote, studio_board as SB
from chloe.studio import PROJECTS


def make(name, scenes=3, clips=0, film=False, covers=0, shorts=0, published=False, ratio="16:9", mode="anim"):
    f = PROJECTS / name
    f.mkdir(parents=True, exist_ok=True)
    (f / "project.json").write_text(json.dumps({"title": name, "scenes": [{"picture": "p", "narration": "n"}] * scenes,
                                                "mode": mode, "ratio": ratio, "created": time.time()}), encoding="utf-8")
    for i in range(clips):
        (f / "clip{}.mp4".format(i)).write_bytes(b"x")
    (f / "clip9.part.mp4").write_bytes(b"x")              # недоделанный клип не считается
    pub = f / "к публикации"
    if film:
        pub.mkdir(exist_ok=True)
        (pub / "ролик.mp4").write_bytes(b"x")
    for i in range(covers):
        from PIL import Image

        Image.new("RGB", (64, 36), (200, 0, 0)).save(pub / "обложка-{}.jpg".format(i + 1))
    if shorts:
        (pub / "shorts").mkdir(parents=True, exist_ok=True)
        (pub / "shorts" / "short-1.mp4").write_bytes(b"x")
    if published:
        (f / "board.json").write_text(json.dumps({"published": time.time()}))
    return f


class Board(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(PROJECTS, ignore_errors=True)
        SB.IDEAS_FILE.unlink(missing_ok=True)

    def test_stages(self):
        make("a-script")
        make("b-preview", clips=1)
        make("c-film", clips=3, film=True)
        make("d-package", clips=3, film=True, covers=1)
        make("e-shorts", clips=3, film=True, covers=1, shorts=1)
        make("f-out", clips=3, film=True, covers=1, published=True)
        got = {e["title"]: e["stage"] for e in SB.episodes()}
        self.assertEqual(got, {"a-script": "script", "b-preview": "preview", "c-film": "film", "d-package": "package",
                               "e-shorts": "shorts", "f-out": "published"})
        self.assertEqual(SB.episodes()[-1]["title"], "f-out")       # вышедшие — в конце
        self.assertEqual([e for e in SB.episodes() if e["title"] == "b-preview"][0]["clips"], 1)

    def test_running_job_shown(self):
        make("кот", clips=1)
        with mock.patch.object(SB, "_running", return_value={"кот": {"kind": "preview", "step": "готово сцен: 2 из 3", "since": 0}}):
            e = SB.episodes()[0]
        self.assertEqual(e["job"]["step"], "готово сцен: 2 из 3")
        with mock.patch.object(SB, "_running", return_value={"кот": {"kind": "film", "step": "x", "since": 0}}):
            self.assertIn("уже идёт", SB.action(str(PROJECTS / "кот"), "continue")["error"])

    def test_cover_thumb_and_published(self):
        f = make("x", clips=3, film=True, covers=1)
        self.assertTrue(SB.cover(str(f)).startswith("data:image/jpeg;base64,"))
        self.assertTrue(SB.action(str(f), "published", "https://youtu.be/x")["ok"])
        e = SB.episode(f)
        self.assertEqual((e["stage"], e["link"]), ("published", "https://youtu.be/x"))
        SB.action(str(f), "unpublished")
        self.assertEqual(SB.episode(f)["stage"], "package")

    def test_only_own_folders(self):
        import tempfile

        other = tempfile.mkdtemp()
        (__import__("pathlib").Path(other) / "project.json").write_text("{}")
        self.assertIn("error", SB.action(other, "published"))
        self.assertEqual(SB.cover(other), "")
        self.assertIn("error", SB.action(str(PROJECTS / ".." / ".."), "open_folder"))

    def test_continue_goes_through_run_tool(self):
        f = make("y", clips=1)
        with mock.patch("chloe.tools.run_tool") as rt, mock.patch("threading.Thread") as th:
            th.side_effect = lambda target, args, **kw: mock.Mock(start=lambda: target(*args))
            SB.action(str(f), "continue")
        rt.assert_called_with("make_film", {"action": "continue", "project": str(f), "open": False})

    def test_ideas_and_tool(self):
        from chloe.tools import HANDLERS

        out = HANDLERS["episodes"]({"action": "add_idea", "ideas": ["Пиксель и дождь", "пиксель и дождь", "Кот и мышь"], "why": "погода заходит"})
        self.assertIn("2", out)
        self.assertEqual([i["text"] for i in SB.ideas()], ["Пиксель и дождь", "Кот и мышь"])
        self.assertEqual(SB.ideas()[0]["source"], "Chloe")
        SB.remove_idea(SB.ideas()[0]["id"])
        self.assertEqual(len(SB.ideas()), 1)

    def test_make_from_idea_uses_make_film(self):
        item = SB.add_idea("Пиксель и дождь")
        with mock.patch("chloe.tools.run_tool", return_value="Начала пробный кусок (#1)") as rt, \
                mock.patch("threading.Thread") as th:
            th.side_effect = lambda target, daemon=None, name=None: mock.Mock(start=target)
            SB.make_from_idea(item["id"], "anim", "9:16", 20)
        args = rt.call_args[0][1]
        self.assertEqual((args["idea"], args["mode"], args["ratio"], args["duration"]), ("Пиксель и дождь", "anim", "9:16", 20))
        self.assertEqual(SB.ideas(), [])                       # серия началась — идея ушла на доску

    def test_phone_cannot_use_studio(self):
        for name in ("studio_action", "studio_make", "studio_idea_add", "studio_board"):
            self.assertNotIn(name, remote.ALLOWED)


if __name__ == "__main__":
    unittest.main()
