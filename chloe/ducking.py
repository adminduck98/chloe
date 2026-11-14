"""Приглушение звука других программ, пока с Chloe говорят и пока она отвечает (как у умных колонок).

Зачем (14.11.2026): когда играет музыка, микрофон слышит её как речь — Chloe ждала конца фразы до 8 с, а к просьбе
приклеивались слова из песни («Яндекс Сортировочный Открой YouTube…»). Теперь: фраза обращена к Chloe или она
начала говорить — музыка, видео и всё остальное тихнут до CHLOE_DUCK % (по умолчанию 20), после ответа — как было.
Свой голос Chloe (её процесс) не трогается. Громкость, которую пользователь сам поменял за это время, не
возвращается назад. CHLOE_DUCK=off — выключить. Linux: PulseAudio / PipeWire через pactl.
"""
import json
import os
import shutil
import subprocess
import threading

_raw = os.environ.get("CHLOE_DUCK", "20").strip().lower()
LEVEL = 0 if _raw in ("off", "0", "no", "") else max(1, min(int(_raw) if _raw.isdigit() else 20, 90))
MAX_SECONDS = 40          # подстраховка: дольше не держим звук приглушённым, даже если что-то забыло вернуть
_lock = threading.Lock()
_saved = {}               # номер потока → (его громкость до приглушения в %, громкость, которую поставили мы)
# программа → (её громкость до приглушения, приглушённая): PipeWire запоминает громкость программы, и новое видео в
# Firefox, начатое во время ответа, сразу играет приглушённым — его тоже надо вернуть (14.11.2026 застревало на 20 %)
_apps = {}
_timer = None
_ENV = dict(os.environ, LC_ALL="C")   # без русской локали pactl не ругается на «non-ASCII» в названиях


def available():
    return bool(LEVEL) and shutil.which("pactl") is not None


def _streams():
    """Потоки звука; None — список не прочитался (pactl не ответил или ответил не JSON)."""
    try:
        r = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True, timeout=5, env=_ENV)
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout or "[]")
        return data if isinstance(data, list) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _percent(stream):
    vols = [int(str(v.get("value_percent", "100%")).rstrip("%") or 100) for v in (stream.get("volume") or {}).values()]
    return max(vols) if vols else 100


def _set(index, percent):
    subprocess.run(["pactl", "set-sink-input-volume", str(index), "{}%".format(percent)], capture_output=True, timeout=3,
                   env=_ENV)


def _app(stream):
    props = stream.get("properties") or {}
    return props.get("application.name") or props.get("application.process.binary") or ""


def mine(stream, pid=None):
    """Поток самой Chloe (её голос и звуки) — его не приглушаем."""
    own = str(pid or os.getpid())
    return str((stream.get("properties") or {}).get("application.process.id", "")) == own


def duck():
    """Приглушить всё, кроме Chloe. Повторный вызов продлевает приглушение и захватывает новые потоки."""
    global _timer
    if not available():
        return
    with _lock:
        for s in _streams() or []:
            idx = s.get("index")
            if idx is None or mine(s) or idx in _saved:
                continue
            app, cur = _app(s), _percent(s)
            if app in _apps and abs(cur - _apps[app][1]) <= 1:
                was, target = _apps[app]              # новый поток уже приглушён (PipeWire запомнил программу)
            else:
                was = cur
                target = max(1, round(was * LEVEL / 100))
                if was <= target:
                    continue
                _set(idx, target)
            _saved[idx] = (was, target)
            _apps.setdefault(app, (was, target))
        if _timer:
            _timer.cancel()
        _timer = threading.Timer(MAX_SECONDS, release)
        _timer.daemon = True
        _timer.start()


def release(after=0.0):
    """Вернуть громкость. after — через сколько секунд (если за это время снова не приглушили)."""
    global _timer
    if after > 0:
        with _lock:
            if _timer:
                _timer.cancel()
            _timer = threading.Timer(after, release)
            _timer.daemon = True
            _timer.start()
        return
    with _lock:
        if _timer:
            _timer.cancel()
            _timer = None
        if not _saved and not _apps:
            return
        streams = _streams()
        if streams is None:                     # список не прочитался — не забываем громкость, пробуем ещё раз
            _timer = threading.Timer(2.0, release)
            _timer.daemon = True
            _timer.start()
            return
        for st in streams:
            idx, cur = st.get("index"), _percent(st)
            if idx in _saved:
                was, target = _saved[idx]
            elif _app(st) in _apps:
                was, target = _apps[_app(st)]       # поток появился во время ответа и унаследовал приглушение
            else:
                continue
            if abs(cur - target) <= 1:              # пользователь не трогал — возвращаем как было
                _set(idx, was)
        _saved.clear()                          # пропавшие потоки (музыка кончилась) возвращать некуда
        _apps.clear()


def ducked():
    return bool(_saved or _apps)

