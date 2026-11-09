"""Связь Python ↔ страница мозга: всё, что одна сторона вызывает, у другой есть.

Такие поломки не ловят обычные тесты: при слиянии версий мозга пропала функция serializeBrain,
и кнопка «Забыть» тихо перестала работать. Эта проверка читает код и ничего не запускает."""
import pathlib
import re
import unittest

from chloe.app import Api

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "chloe" / "ui"
PAGE = (UI / "chloe-mind.html").read_text(encoding="utf-8")
REMOTE = (UI / "remote.js").read_text(encoding="utf-8")
PY = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "chloe").rglob("*.py"))
SCRIPTS = "\n".join(re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", PAGE, re.S)) + "\n" + REMOTE

# встроенное в браузер и в язык шейдеров GLSL — не наши функции
BUILTIN = {"if", "for", "Audio", "while", "switch", "return", "function", "catch", "typeof", "new", "parseInt", "parseFloat",
           "setTimeout", "setInterval", "clearTimeout", "clearInterval", "String", "Number", "Boolean", "Math", "JSON",
           "Date", "Array", "Object", "isNaN", "isFinite", "Float32Array", "Uint8Array", "Uint16Array", "Uint32Array",
           "Int32Array", "requestAnimationFrame", "cancelAnimationFrame", "encodeURIComponent", "decodeURIComponent",
           "RegExp", "URLSearchParams", "Error", "Image", "Promise", "Map", "Set", "Event", "Proxy", "fetch", "alert",
           "confirm", "SpeechSynthesisUtterance", "KeyboardEvent",
           "abs", "cross", "distance", "exp", "floor", "fract", "fwidth", "length", "max", "min", "mix", "mod", "normalize", "pow",
           "sin", "cos", "smoothstep", "texture2D", "vec2", "vec3", "vec4", "clamp", "step", "dot", "sqrt", "main", "rgba",
           "calc", "env", "onArrive", "then", "cb", "onDone", "onThink", "after", "rng", "f", "Rec", "reply", "fn", "job", "done", "reopen", "fromApi"}


class Bridge(unittest.TestCase):
    def test_every_brain_call_from_python_exists_in_page(self):
        called = set(re.findall(r"""\bjs\(\s*["'](chloe\w+)["']""", PY))
        defined = set(re.findall(r"window\.(chloe\w+)\s*=", SCRIPTS))
        self.assertTrue(called)
        self.assertEqual(called - defined, set(), "Python зовёт в мозге то, чего там нет")

    def test_every_api_call_from_page_exists_in_python(self):
        called = set(re.findall(r"\b(?:api|pywebview\.api|jApi\(\))\.(\w+)\(", SCRIPTS))
        missing = {n for n in called if not callable(getattr(Api, n, None))}
        self.assertTrue(called)
        self.assertEqual(missing, set(), "страница зовёт в Python то, чего там нет")

    def test_no_calls_to_missing_functions(self):
        code = re.sub(r"//[^\n]*", "", SCRIPTS)
        calls = set(re.findall(r"(?<![\w.$])([a-zA-Z_]\w*)\s*\(", code))
        defs = set(re.findall(r"function\s+([a-zA-Z_]\w*)", code)) | set(re.findall(r"([a-zA-Z_]\w*)\s*=\s*function", code)) \
            | set(re.findall(r"var\s+([a-zA-Z_]\w*)\s*=", code)) \
            | set(re.findall(r"(?:float|vec[234]|void)\s+(\w+)\s*\(", code))   # функции шейдеров GLSL
        self.assertEqual(calls - defs - BUILTIN, set(), "страница зовёт функции, которых нет")


if __name__ == "__main__":
    unittest.main()
