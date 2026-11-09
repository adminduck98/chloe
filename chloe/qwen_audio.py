"""Голос и слух через Qwen (Alibaba Model Studio): синтез речи qwen-audio-…-tts и распознавание qwen-audio-…-asr.

Работает и с подпиской Token Plan (ключ sk-sp-…, тратятся кредиты подписки), и с обычным ключом (по факту).
Любой сбой — исключение: voice.py тогда говорит Светланой и слушает через Google, как раньше.
"""
import base64
import json
import os
import urllib.error
import urllib.request

from . import config

TTS_MODEL = os.environ.get("CHLOE_QWEN_TTS_MODEL", "qwen-audio-3.0-tts-plus")
ASR_MODEL = os.environ.get("CHLOE_QWEN_ASR_MODEL", "qwen-audio-3.0-asr-flash")
VOICE = os.environ.get("CHLOE_QWEN_VOICE", "longanlingxin")   # многоязычный женский голос; по-русски говорит разборчиво
RATE = 24000


class NoSpeech(Exception):
    """Сервер не нашёл в записи речи: обрывок короче ~0,3 с или тишина (он отвечает на это «400 {}»). Не поломка."""


def available():
    return bool(config.QWEN_KEY)


def native_base():
    """Адрес «родного» API DashScope рядом с OpenAI-совместимым: …/compatible-mode/v1 → корень."""
    from .thinking.openai_chat import qwen_base_url

    return qwen_base_url().split("/compatible-mode")[0].rstrip("/")


def _request(path, body, stream=False, timeout=30):
    headers = {"Authorization": "Bearer " + config.QWEN_KEY, "Content-Type": "application/json",
               "X-DashScope-SSE": "enable" if stream else "disable"}
    req = urllib.request.Request(native_base() + path, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:   # «400 Bad Request» сам по себе ничего не говорит — нужен ответ сервера
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("HTTP {}: {}".format(e.code, detail)) from None


def tts_stream(text, voice=None, timeout=30):
    """mp3 кусочками по мере синтеза (первый звук ~1 с). Генератор байтов."""
    body = {"model": TTS_MODEL, "input": {"text": text, "voice": voice or VOICE, "format": "mp3", "sample_rate": RATE}}
    with _request("/api/v1/services/audio/tts/SpeechSynthesizer", body, stream=True, timeout=timeout) as r:
        for line in r:
            line = line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = json.loads(line[5:])
            if data.get("code") and not data.get("output"):
                raise RuntimeError("Qwen TTS: {} {}".format(data.get("code"), data.get("message", ""))[:200])
            chunk = ((data.get("output") or {}).get("audio") or {}).get("data")
            if chunk:
                yield base64.b64decode(chunk)


def tts_mp3(text, voice=None, timeout=30):
    """Вся фраза одним mp3 — для телефона и для озвучки целым файлом."""
    data = b"".join(tts_stream(text, voice, timeout))
    if not data:
        raise RuntimeError("Qwen TTS: пустой ответ")
    return data


def asr(wav_bytes, language="ru", timeout=20):
    """Текст из записи WAV (16 кГц, 16 бит, моно). Пустая строка — речи не было."""
    body = {"model": ASR_MODEL,
            "input": {"messages": [{"role": "user", "content": [
                {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode()}}]}]},
            "parameters": {"format": "wav", "sample_rate": "16000", **({"language_hints": [language]} if language else {})}}
    try:
        r = _request("/api/v1/services/aigc/multimodal-generation/generation", body, timeout=timeout)
    except RuntimeError as e:
        if str(e).startswith("HTTP 400"):
            raise NoSpeech(str(e)) from None
        raise
    with r:
        data = json.load(r)
    out = data.get("output") or {}
    text = out.get("text")
    if text is None:   # формат как у чата: output.choices[0].message.content
        try:
            content = out["choices"][0]["message"]["content"]
            text = content if isinstance(content, str) else "".join(c.get("text", "") for c in content)
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("Qwen ASR: неожиданный ответ " + json.dumps(data, ensure_ascii=False)[:200])
    return text.strip()
