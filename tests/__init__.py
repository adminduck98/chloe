"""Тесты Chloe. Запуск из папки проекта:  .venv/bin/python -m unittest

Тесты работают во временной домашней папке: настоящие ~/.chloe (память, журнал, мозг) не трогаются,
и никаких ключей не нужно — модели подменяются поддельными."""
import os
import tempfile

os.environ.setdefault("CHLOE_REAL_HOME", os.environ.get("HOME", ""))   # только читать: модели Vosk и Piper
# одна временная папка на весь запуск, даже если этот файл выполнится повторно
os.environ.setdefault("CHLOE_TEST_HOME", tempfile.mkdtemp(prefix="chloe-test-"))
os.environ["HOME"] = os.environ["CHLOE_TEST_HOME"]
for _key in ("XDG_DATA_HOME", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "QWEN_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "CHLOE_PROVIDER", "CHLOE_MODEL", "CHLOE_CONFIRM"):
    os.environ.pop(_key, None)
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["CHLOE_STREAM_VOICE"] = "off"   # потоковый голос ходит в сеть и в звуковую карту — у него свои тесты с подменой

# защита: если пакет chloe уже загружен с настоящей домашней папкой, тесты испортили бы настоящие память и журнал
import sys as _sys

if "chloe.config" in _sys.modules and str(_sys.modules["chloe.config"].HOME) != os.environ["HOME"]:
    raise RuntimeError("chloe загружен раньше тестов — запускайте: .venv/bin/python -m unittest discover -s tests -t .")
