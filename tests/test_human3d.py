"""3D-человек из Blender: где Blender, команда запуска, предметы по времени, сборка видео из кадров, инструмент.
Blender здесь не запускается — процесс подменён."""
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from chloe import human3d as H3
from chloe import mocap as MC


class Find(unittest.TestCase):
    def test_env_then_local_then_path(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        exe = tmp / "blender"
        exe.write_text("")
        with mock.patch.dict(os.environ, {"CHLOE_BLENDER": str(exe)}):
            self.assertEqual(H3.blender_path(), str(exe))
        with mock.patch.dict(os.environ, {"CHLOE_BLENDER": ""}), \
                mock.patch.object(H3.glob, "glob", return_value=["/a/blender-5.1.0/blender", "/a/blender-5.2.4/blender"]):
            self.assertEqual(H3.blender_path(), "/a/blender-5.2.4/blender")      # новейший
        with mock.patch.dict(os.environ, {"CHLOE_BLENDER": ""}), mock.patch.object(H3.glob, "glob", return_value=[]), \
                mock.patch.object(H3.shutil, "which", return_value=None):
            self.assertIsNone(H3.blender_path())
            self.assertFalse(H3.available())
            self.assertIn("Blender", H3.why_not())


class Command(unittest.TestCase):
    def test_props_are_cleaned_and_sorted(self):
        props = H3.norm_props([{"at": 0.5, "prop": "pistol"}, {"at": -1, "prop": "rifle"}, {"at": 0.2, "prop": "bazooka"},
                               "мусор", {"at": "x", "prop": "rifle"}, {"at": 0.9, "prop": None}])
        self.assertEqual(props, [{"at": 0.0, "prop": "rifle"}, {"at": 0.5, "prop": "pistol"}, {"at": 0.9, "prop": None}])

    def test_command_line(self):
        with mock.patch.object(H3, "blender_path", return_value="/b/blender"):
            cmd = H3.command("m.json", "/out", view="наискосок", size=(640, 360), outfit="чужое", props=[{"at": 0, "prop": "rifle"}],
                             cloth=False)
        self.assertEqual(cmd[:4], ["/b/blender", "-b", "-P", str(H3.SCRIPT)])
        args = dict(zip(cmd[5::2], cmd[6::2]))
        self.assertEqual(args["--view"], "34")                                 # неизвестный вид — вполоборота
        self.assertEqual(args["--outfit"], "male_casualsuit04")
        self.assertEqual(args["--size"], "640x360")
        self.assertEqual(args["--cloth"], "0")
        self.assertEqual(json.loads(args["--props"]), [{"at": 0.0, "prop": "rifle"}])
        self.assertTrue(H3.SCRIPT.exists())

    def test_estimate(self):
        self.assertEqual(H3.estimate(237, "nvidia"), 5)
        self.assertEqual(H3.estimate(237, "intel"), 11)

    def test_blender_goes_to_nvidia_when_it_works(self):
        with mock.patch.object(H3, "nvidia_ready", return_value=True):
            env = H3.gpu_env()
        self.assertEqual(env["__NV_PRIME_RENDER_OFFLOAD"], "1")
        with mock.patch.object(H3, "nvidia_ready", return_value=False), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("__NV_PRIME_RENDER_OFFLOAD", None)
            self.assertNotIn("__NV_PRIME_RENDER_OFFLOAD", H3.gpu_env())
        with mock.patch.dict(os.environ, {"CHLOE_BLENDER_GPU": "intel"}):
            self.assertFalse(H3.nvidia_ready())                            # можно заставить рисовать на Intel


REAL_POPEN = H3.subprocess.Popen


class FakeProc:
    """Как Blender: пишет кадры в папку из --out и строки прогресса (другие команды — настоящий процесс)."""

    def __new__(cls, cmd, **kw):
        if "--out" not in cmd:
            return REAL_POPEN(cmd, **kw)
        return super().__new__(cls)

    def __init__(self, cmd, **kw):
        out = pathlib.Path(cmd[cmd.index("--out") + 1])
        lines = []
        for i in range(1, 4):
            (out / "f{:04d}.png".format(i)).write_bytes(b"png")
            lines.append("КАДР {} 3\n".format(i))
        self.stdout = io.StringIO("".join(lines) + "ГОТОВО 3\n")

    def wait(self):
        return 0


class Render(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lib = {"drill": {"poses": [{}] * 3, "body3d": [{"hip1": [0, 0, 0]}] * 3, "face3d": -70, "fps": 25},
                    "old": {"poses": [{}] * 3, "fps": 25}}

    def test_frames_become_video(self):
        seen, ff = [], []
        with mock.patch.object(H3, "available", return_value=True), mock.patch.object(MC, "library", return_value=self.lib), \
                mock.patch.object(H3.subprocess, "Popen", FakeProc), \
                mock.patch("chloe.studio.run_ffmpeg", side_effect=lambda a, timeout=0: ff.append(a)):
            out = H3.render("drill", self.tmp / "v.mp4", progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(out, self.tmp / "v.mp4")
        self.assertEqual(seen[-1], (3, 3))
        self.assertIn("-start_number", ff[0])

    def test_needs_3d_skeleton_and_blender(self):
        with mock.patch.object(H3, "available", return_value=True), mock.patch.object(MC, "library", return_value=self.lib):
            with self.assertRaises(H3.Human3DError):
                H3.render("old", self.tmp / "v.mp4")
        with mock.patch.object(H3, "available", return_value=False), mock.patch.object(H3, "why_not", return_value="нет Blender"):
            with self.assertRaises(H3.Human3DError):
                H3.render("drill", self.tmp / "v.mp4")


class Tool(unittest.TestCase):
    def test_tool_answers(self):
        from chloe.tools import media

        with mock.patch.object(H3, "available", return_value=False), mock.patch.object(H3, "why_not", return_value="нет Blender"):
            self.assertIn("недоступен", media.tool_learn_move({"action": "human3d", "name": "drill"}))
        with mock.patch.object(H3, "available", return_value=True), \
                mock.patch.object(MC, "library", return_value={"x": {"poses": [], "body3d": [{}]}}):
            self.assertIn("Есть: x", media.tool_learn_move({"action": "human3d", "name": "нет_такого"}))
            with mock.patch.object(media, "_start", return_value=7) as start:
                reply = media.tool_learn_move({"action": "human3d", "name": "x", "prop": "rifle", "open": False})
        self.assertIn("#7", reply)
        self.assertIn("rifle", reply)
        self.assertEqual(start.call_args[0][0], "human3d")


if __name__ == "__main__":
    unittest.main()
