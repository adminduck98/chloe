"""Инструмент my_voice — свой голос Chloe: показать, поменять (скорость, высота, громкость, паузы, эмоции), послушать."""
from .. import persona

STEP = {"rate": 6, "pitch": 3, "volume": 8}
ADJUST = {"faster": ("rate", 1), "slower": ("rate", -1), "higher": ("pitch", 1), "lower": ("pitch", -1),
          "louder": ("volume", 1), "quieter": ("volume", -1)}


def tool_my_voice(a):
    action = a.get("action", "show")
    if action == "show":
        return persona.describe()
    if action == "reset":
        persona.reset()
        return "Вернула свой обычный голос. " + persona.describe()
    if action in ADJUST:
        key, sign = ADJUST[action]
        n = int(a.get("steps") or 1)
        persona.change(**{key: persona.profile()[key] + sign * STEP[key] * max(1, min(n, 4))})
        return "Поменяла. " + persona.describe() + " Скажи пару слов новым голосом, чтобы пользователь услышал."
    if action == "set":
        fields = {k: a[k] for k in ("rate", "pitch", "volume") if a.get(k) is not None}
        if a.get("pauses") in ("short", "normal", "long"):
            fields["pauses"] = a["pauses"]
        if a.get("emotions") is not None:
            fields["emotions"] = bool(a["emotions"])
        if not fields:
            return "Что поменять: rate, pitch, volume, pauses (short/normal/long) или emotions (true/false)."
        persona.change(**fields)
        return "Поменяла. " + persona.describe()
    if action == "sample":
        from ..voice import voice

        for _mood, text in persona.SAMPLES:
            voice.say(text)
        return "Прочитала четыре пробные фразы: ровно, радостно, мягко и серьёзно. Спроси, что поменять."
    return "Неизвестное действие: " + action


def tool_my_voiceprint(a):
    """Отпечаток голоса владельца: status — знает ли; enroll — «запомни мой голос» (следующие ~25 с только слушает);
    reset — забыть отпечаток (снова только по имени, пока не запомнит заново)."""
    import threading
    import time

    from .. import voiceprint
    from ..signals import busy
    from ..voice import voice

    action = a.get("action", "status")
    if action == "status":
        return voiceprint.status_text()
    if action == "reset":
        voiceprint.reset()
        return "Забыла отпечаток голоса: снова отвечаю только на «Хлоя», пока не запомню заново."
    if action != "enroll":
        return "Неизвестное действие: " + action
    if not voiceprint.available():
        return voiceprint.status_text()
    before = len(voiceprint.samples())

    def window():
        end = time.time() + 40
        while (busy.is_set() or voice.saying) and time.time() < end:   # сначала договорит свой ответ
            time.sleep(0.2)
        time.sleep(0.6)
        voice.enroll_until = time.time() + voiceprint.ENROLL_SECONDS
        time.sleep(voiceprint.ENROLL_SECONDS + 1.5)
        added = len(voiceprint.samples()) - before
        voice.say("Запомнила твой голос, босс: {} новых фраз. {}".format(added, voiceprint.status_text()) if added
                  else "Не расслышала ни одной фразы — давай ещё раз, говори погромче и подольше.")
    threading.Thread(target=window, daemon=True, name="voiceprint-enroll").start()
    return ("Скажи пользователю: после этого ответа {} секунд просто говорить что угодно — фразами по 2–5 секунд, "
            "на любом языке; в это время ты только слушаешь и запоминаешь голос, команды не выполняешь; потом скажешь "
            "результат сама.".format(voiceprint.ENROLL_SECONDS))
