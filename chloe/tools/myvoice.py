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
