"""Словарь движений камеры, приёмов съёмки и переходов — общий язык Хлои с генератором видео.

По мотивам motion-prompt (github.com/showheyohtaki/motion-prompt, MIT): у каждого приёма есть точное название — с ним
нейросеть делает то, что просили, а не «что-то похожее». Формулировки свои. Русское название — как говорит
пользователь; prompt — как просить генератор видео (по-английски, так он понимает точнее); when — когда это к месту.
"""
import re

CAMERA = {
    "static": ("неподвижная камера", "locked-off static camera on a tripod, the camera does not move at all",
               "спокойная сцена, разговор, всё внимание на действии"),
    "pan": ("панорама", "slow pan from left to right, the camera pivots in place", "показать место, проследить за взглядом"),
    "tilt": ("наклон вверх", "tilt up from the ground to the top, the camera pivots in place", "показать высоту, раскрыть масштаб"),
    "dolly_in": ("наезд", "slow dolly in, the camera physically moves toward the subject, foreground passes by",
                 "напряжение растёт, важный момент, эмоция героя"),
    "dolly_out": ("отъезд", "slow dolly out, the camera moves back and reveals the surroundings", "показать, где герой; финал"),
    "zoom_in": ("зум", "zoom in, the camera stays still and only the focal length changes", "резкое внимание, комичный акцент"),
    "tracking": ("сопровождение сбоку", "tracking shot, the camera moves sideways at the same speed as the walking subject",
                 "герой идёт или бежит"),
    "follow": ("за героем", "follow shot, the camera trails the subject from behind at the same distance", "погоня, путь"),
    "orbit": ("облёт", "orbit shot, the camera circles around the subject, background sweeps behind",
              "кульминация, герой в центре внимания"),
    "crane_up": ("кран вверх", "crane up, the camera rises while tilting down onto the subject", "финал, итог, одиночество"),
    "pedestal": ("подъём камеры", "pedestal up, the camera moves straight up without tilting", "раскрыть, что выше"),
    "dolly_zoom": ("эффект головокружения", "dolly zoom (vertigo effect): the subject stays the same size while the background stretches",
                   "шок, осознание"),
    "handheld": ("с рук", "handheld camera with small natural shake", "тревога, документальность, суматоха"),
    "steadicam": ("плавно за героем", "steadicam glide following the subject, smooth gentle sway", "плавное путешествие"),
    "fpv": ("дрон от первого лица", "FPV drone shot flying low and fast, banking between obstacles", "скорость, полёт, экшен"),
    "fly_through": ("пролёт сквозь", "fly-through: the camera flies through an opening into the space beyond", "переход в новый мир"),
    "barrel_roll": ("переворот камеры", "barrel roll, the camera rotates a full turn around its axis", "безумие, кульбит"),
}
ANGLES = {
    "low": ("снизу", "low angle shot looking up, the subject looks big and powerful", "герой силён, угроза"),
    "high": ("сверху", "high angle shot looking down, the subject looks small", "герой слаб, потерян"),
    "birds_eye": ("с высоты птичьего полёта", "bird's-eye view straight down from above", "план местности, узор"),
    "pov": ("глазами героя", "POV shot through the character's eyes, hands visible at the bottom", "погружение, игра"),
    "ots": ("через плечо", "over-the-shoulder shot, the near character's shoulder frames the other", "диалог, противостояние"),
    "dutch": ("заваленный горизонт", "dutch angle, the horizon tilted diagonally", "что-то не так, тревога"),
    "establishing": ("общий план места", "wide establishing shot of the whole place, slow push in", "начало, новое место"),
    "close_up": ("крупный план", "close-up on the face, emotion fills the frame", "эмоция, реакция"),
    "extreme_close_up": ("очень крупно", "extreme close-up on the eyes", "предельное напряжение"),
}
TIME = {
    "slow_motion": ("замедление", "slow motion, the action moves at a fraction of normal speed", "удар, прыжок, красота момента"),
    "speed_ramp": ("ускорение-замедление", "speed ramp: fast motion that smoothly slows down at the key moment", "драка, трюк"),
    "freeze_frame": ("стоп-кадр", "freeze frame at the peak of the action, then the motion resumes", "комичная пауза, акцент"),
    "time_lapse": ("таймлапс", "time-lapse, hours pass in seconds, clouds and shadows race", "прошло время"),
    "bullet_time": ("время застыло", "bullet time: time nearly stops while the camera circles the subject", "кульминация экшена"),
}
TRANSITIONS = {
    "cut": ("склейка", "", "по умолчанию — просто следующий кадр"),
    "match_cut": ("склейка по форме", "the shot ends on a shape that matches the first shape of the next shot", "связать две сцены смыслом"),
    "whip_pan": ("рывок камеры", "whip pan: the camera swings fast with motion blur", "резкая смена места, энергия"),
    "smash_cut": ("резкий контраст", "", "из тишины — в шум, комичный контраст"),
    "jump_cut": ("скачок времени", "", "время прошло, а кадр тот же"),
    "fade_black": ("в затемнение", "fade to black", "конец главы, пауза"),
    "iris_out": ("диафрагма", "iris out: a circle closes on the subject", "мультяшный финал"),
    "j_cut": ("звук раньше картинки", "", "следующая сцена начинается со звука"),
}
EFFECTS = {
    "anticipation": ("замах", "a small wind-up in the opposite direction before the main move", "перед ударом, прыжком, броском"),
    "follow_through": ("доводка", "parts keep moving after the body stops, then settle", "после резкой остановки"),
    "squash_stretch": ("сжатие-растяжение", "squash on impact and stretch in fast motion", "мультяшная упругость"),
    "impact_shake": ("тряска от удара", "a short camera shake on impact", "удар, падение"),
    "motion_trail": ("шлейф движения", "motion trail: fading copies behind a fast object", "скорость"),
    "shatter": ("разлёт осколков", "the object shatters into shards that fly apart", "разбить"),
    "glitch": ("глитч", "digital glitch: the frame tears into shifted slices with color fringes", "сбой, цифровой мир"),
    "particles": ("частицы", "small particles burst out and drift", "магия, праздник"),
}
ALL = {**CAMERA, **ANGLES, **TIME, **TRANSITIONS, **EFFECTS}

# как просят словами (основы слов) → ключ
ALIASES = {"наезд": "dolly_in", "приближ": "dolly_in", "отъезд": "dolly_out", "отдал": "dolly_out", "зум": "zoom_in",
           "панорам": "pan", "облёт": "orbit", "облет": "orbit", "вокруг": "orbit", "дрон": "fpv", "с рук": "handheld",
           "тряск": "impact_shake", "сверху": "high", "снизу": "low", "глазами": "pov", "крупн": "close_up",
           "замедл": "slow_motion", "слоумо": "slow_motion", "стоп-кадр": "freeze_frame", "стоп кадр": "freeze_frame",
           "таймлапс": "time_lapse", "затемн": "fade_black", "головокруж": "dolly_zoom", "сопровожд": "tracking",
           "за героем": "follow", "кран": "crane_up", "глитч": "glitch", "осколк": "shatter", "общий план": "establishing"}


def find(text):
    """Ключ приёма по ключу или словам пользователя («сделай наезд») или None."""
    t = (text or "").strip().lower()
    if t in ALL:
        return t
    for stem, key in ALIASES.items():
        if stem in t:
            return key
    return None


def phrase(key):
    """Фраза для генератора видео (пусто — приём монтажный, генератору не нужен)."""
    return ALL.get(key, ("", "", ""))[1]


def catalog(groups=("camera", "angles", "time")):
    """Список для сценариста: «ключ — что это — когда к месту»."""
    src = {"camera": CAMERA, "angles": ANGLES, "time": TIME, "transitions": TRANSITIONS, "effects": EFFECTS}
    return "\n".join("- {} — {}: {}".format(k, v[0], v[2]) for g in groups for k, v in src[g].items())


STAMP = re.compile(r"\[\s*(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*s?\s*\]")


def fit_timeline(video, secs):
    """«[0–3s] … [3–6s] …» от сценариста → под настоящую длину клипа (сценарист не знает, сколько продлится голос)."""
    stamps = [(float(a), float(b)) for a, b in STAMP.findall(video or "")]
    if not stamps:
        return video or ""
    total = max(b for _a, b in stamps) or 1.0
    k = secs / total
    return STAMP.sub(lambda m: "[{:.1f}–{:.1f}s]".format(float(m.group(1)) * k, float(m.group(2)) * k), video)


def video_prompt(scene, secs, style=""):
    """Задание генератору видео для сцены: движение камеры из словаря, план, действия со временем под длину клипа,
    требование не менять героя с первого кадра."""
    parts = []
    for key in (scene.get("camera_move"), scene.get("angle"), scene.get("time_effect")):
        k = find(key) if key else None
        if k and phrase(k):
            parts.append(phrase(k))
    timeline = fit_timeline(scene.get("video") or "", secs)
    if timeline:
        parts.append(timeline)
    elif scene.get("picture"):
        parts.append(scene["picture"])
    parts.append("Keep every character exactly as in the first frame: same face, body, colors and clothes. "
                 "Smooth natural motion, no text on screen.")
    if style:
        parts.append(style)
    return " ".join(p.strip().rstrip(".") + "." for p in parts if p.strip())
