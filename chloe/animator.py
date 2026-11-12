"""Свой мультипликатор: человечки из палочек рисуются и двигаются прямо на компьютере — бесплатно, без интернета,
без ограничения длины, один и тот же герой в каждом кадре.

Как устроено:
- у человечка скелет: голова, шея, туловище, руки (плечо + локоть), ноги (бедро + колено); поза — набор углов;
- движения: позы (стоит, указывает, думает, ура…) и циклы (идёт, бежит, машет, говорит, танцует, дерётся, прыгает);
  между движениями — плавный переход, походка сама двигает героя к цели и разворачивает его;
- лицо меняется по эмоции (рад, грустит, злится, удивлён, думает); предметы в руке, предметы на сцене, значки над головой;
- камера: приближение к герою, тряска на ударе;
- фон — по стилю (светлый, тёмный, неон на экране компьютера) или картинка места (смешанный режим: фон рисует нейросеть).

Сцену описывает мозг (сценарист) — JSON «кто что делает и когда», время — доли длины сцены, длину задаёт голос.
Рисуется cairo (гладкие линии, ~0,5 мс на кадр), кадры сразу уходят в ffmpeg вместе с голосом, субтитрами и звуками.
"""
import logging
import math
import pathlib
import subprocess

log = logging.getLogger("chloe.animator")

FPS = 25
GROUND = 0.84            # линия земли — доля высоты кадра
FIG = 0.40               # рост человечка — доля высоты кадра
BLEND = 0.22             # секунд: плавный переход между движениями
# удары: (раз в секунду, доля цикла, где рука/нога дальше всего — кадр удара). Перед ним замах, после — отдача
STRIKE = {"punch": (1.6, 0.24), "fight": (3.0, 0.24), "kick": (1.4, 0.26)}
# отлёт от удара: всего секунд; доли — полёт дугой, юзом по полу, подъём
KNOCK_TIME, KNOCK_FLY, KNOCK_SLIDE = 1.5, 0.3, 0.55
RAG_RISE = 0.7           # секунд: встаёт после падения по физике
TRASH_IN, TRASH_OUT = 0.35, 0.6   # секунд: проваливается в корзину; выпрыгивает из неё
REACH = 0.24             # длина удара в долях высоты кадра: на таком расстоянии от цели встаёт нападающий
# суставы догоняют позу, как пружина: чуть запаздывают и чуть проскакивают — движение с инерцией, а не рывками
SPRING_W = 30.0          # рад/с: жёсткость (больше — быстрее догоняет)
SPRING_Z = 0.62          # затухание: меньше 1 — лёгкий «довод» после остановки

# длины частей тела в долях роста
SEG = {"head": 0.095, "neck": 0.035, "torso": 0.30, "upper": 0.165, "fore": 0.155, "thigh": 0.215, "shin": 0.215}

COLORS = {"black": (0.07, 0.07, 0.07), "white": (0.96, 0.96, 0.96), "red": (0.95, 0.27, 0.27), "blue": (0.25, 0.55, 1.0),
          "green": (0.25, 0.85, 0.45), "yellow": (1.0, 0.82, 0.2), "orange": (1.0, 0.55, 0.15), "purple": (0.7, 0.4, 1.0),
          "pink": (1.0, 0.45, 0.7), "cyan": (0.2, 0.9, 0.95), "gray": (0.55, 0.55, 0.55), "graphite": (0.2, 0.2, 0.22)}
ACCENT = {"red": (0.92, 0.25, 0.25), "blue": (0.22, 0.5, 0.95), "gold": (0.98, 0.75, 0.18)}

# Оформление по стилю: фон, цвет героя, свечение линий, залитая голова
LOOKS = {
    "classic_light": {"bg": (1, 1, 1), "ink": "black", "glow": 0.0, "ground": (0.86, 0.86, 0.86), "filled_head": False},
    "classic_dark": {"bg": (0.04, 0.04, 0.05), "ink": "white", "glow": 0.35, "ground": (0.2, 0.2, 0.22), "filled_head": False},
    "neon_desktop": {"bg": "desktop", "ink": "cyan", "glow": 0.75, "ground": None, "filled_head": True, "trails": True, "flash": True},
    # экшен: толстые линии с тёмной обводкой, залитая голова, растяжки на быстрых движениях, искры и обломки, кадр-негатив
    # на сильном ударе, пауза на ударе, камера сама следит за дракой (свои герои; приёмы — как у профессиональных драк)
    "action": {"bg": "desktop", "ink": "cyan", "glow": 0.0, "ground": None, "filled_head": True, "thick": True, "smear": True,
               "impact": True, "flash": True, "camera": "follow", "hitstop": True, "physics": True},
    "beanie": {"bg": (0.97, 0.98, 1.0), "ink": "black", "glow": 0.0, "ground": (0.82, 0.86, 0.9), "filled_head": False, "beanie": True},
    "cozy": {"bg": (0.98, 0.95, 0.9), "ink": "black", "glow": 0.0, "ground": (0.8, 0.74, 0.66), "filled_head": True},
    "prehistoric": {"bg": (0.93, 0.86, 0.74), "ink": "black", "glow": 0.0, "ground": (0.62, 0.5, 0.36), "filled_head": True},
    "historical": {"bg": (0.95, 0.92, 0.85), "ink": "black", "glow": 0.0, "ground": (0.7, 0.62, 0.5), "filled_head": True},
    # белая доска (по мотивам srt-whiteboard-animation, MIT): тёплая бумага #F5EBD7, графитовый маркер, акценты — только
    # красный, синий, оранжевый; всё появляется под маркером по порядку рассказа, камера не плывёт
    "whiteboard": {"bg": (0.961, 0.922, 0.843), "ink": "graphite", "glow": 0.0, "ground": (0.45, 0.43, 0.4), "filled_head": False,
                   "draw": True, "still": True, "others": ("red", "blue", "orange")},
}

# --- позы: углы в градусах; 0 — вниз, плюс — вперёд (куда смотрит герой). Локоть и колено — сгиб относительно плеча/бедра.
#     torso — наклон туловища, head — наклон головы, dy — подъём таза (доля роста), rot — поворот всего тела (лёжа, падение)
BASE = {"torso": 0, "head": 0, "sh1": 8, "el1": 10, "sh2": -8, "el2": 10, "hip1": 4, "kn1": -4, "hip2": -4, "kn2": -4, "dy": 0, "rot": 0}
POSES = {
    "stand": {},
    "point": {"sh1": 92, "el1": 4, "head": 6},
    "think": {"sh1": 30, "el1": 135, "head": -10, "sh2": 20, "el2": 70},
    "cheer": {"sh1": 140, "el1": 25, "sh2": -140, "el2": -25, "head": -12},
    "shrug": {"sh1": 50, "el1": 110, "sh2": -50, "el2": -110, "head": 8},
    "sit": {"hip1": 90, "kn1": -90, "hip2": 80, "kn2": -86, "dy": -0.215, "torso": -4, "sh1": 30, "el1": 50, "sh2": 20, "el2": 50},
    "crouch": {"hip1": 70, "kn1": -125, "hip2": 50, "kn2": -115, "dy": -0.17, "torso": 22, "sh1": 40, "el1": 30, "sh2": 25, "el2": 30},
    "facepalm": {"sh1": 40, "el1": 150, "head": 18, "torso": 6, "sh2": -6, "el2": 10},
    "sad": {"head": 26, "torso": 10, "sh1": 2, "el1": 4, "sh2": -2, "el2": 4},
    "surprised": {"sh1": 115, "el1": 35, "sh2": -115, "el2": -35, "head": -14, "torso": -8},
    "hold": {"sh1": 40, "el1": 70},
    "type": {"sh1": 55, "el1": 45, "sh2": 45, "el2": 50, "torso": 8, "head": 10},
    "push": {"sh1": 88, "el1": 0, "sh2": 80, "el2": 0, "torso": 28, "hip1": 28, "kn1": -18, "hip2": -24, "kn2": -10},
    "lie": {"rot": 90, "dy": -0.48, "sh1": 170, "el1": 0, "sh2": 160, "el2": 0},
    "angry": {"sh1": 25, "el1": 100, "sh2": -25, "el2": -100, "torso": 6, "head": 6},
    "catch": {"sh1": 80, "el1": 25, "sh2": 70, "el2": 30, "torso": -4, "hip1": 14, "kn1": -12, "hip2": -10},
    "hug": {"sh1": 72, "el1": 75, "sh2": 62, "el2": 85, "torso": 8, "head": 10},
    "bow": {"torso": 55, "head": 20, "sh1": 4, "el1": 6, "sh2": -2, "el2": 6},
    "give": {"sh1": 70, "el1": 12, "torso": 6, "head": 8},
}
EMOTION_OF = {"hug": "happy", "catch": "surprised", "cheer": "happy", "sad": "sad", "surprised": "surprised", "think": "think", "facepalm": "sad", "angry": "angry",
              "shrug": "neutral", "dance": "happy", "fight": "angry", "punch": "angry", "kick": "angry", "fall": "surprised"}
MOCAP_MOVES = ("jumpkick", "spinkick", "backflip", "sideflip", "cartwheel", "faceplant", "slip", "rugpull",
               "duck", "slide", "roll", "breakdance", "kazachok", "moonwalk", "ballet", "guard", "diveroll")   # из живых записей
ACTIONS = sorted(set(POSES) | set(MOCAP_MOVES) | {"walk", "run", "jump", "wave", "talk", "dance", "fight", "punch", "kick", "fall", "idle",
                                "crawl", "climb", "throw", "fly", "sneak"})
MOVING = ("walk", "run", "sneak", "crawl", "fly")
FRONT = ("cheer", "shrug", "surprised", "dance", "wave", "bow")   # эти позы — лицом к зрителю: так живее
EMOTIONS = ("neutral", "happy", "sad", "angry", "surprised", "think")
# похожие слова, которыми модель называет движения, — к своим (иначе герой стоял бы столбом)
SYNONYMS = {"block": "guard", "defend": "guard", "parry": "guard", "dive_roll": "diveroll", "dodge": "duck", "evade": "duck", "slide_tackle": "slide", "tackle": "slide", "somersault_roll": "roll",
            "dive": "roll", "break_dance": "breakdance", "russian_dance": "kazachok", "moon_walk": "moonwalk",
            "pirouette": "ballet", "flip": "backflip", "somersault": "backflip", "trip": "slip", "stumble": "slip", "tumble": "faceplant",
            "handspring": "cartwheel", "flying_kick": "jumpkick", "spin_kick": "spinkick", "drag": "push", "pull": "push", "lift": "push", "freeze": "surprised", "scared": "surprised", "shock": "surprised",
            "gasp": "surprised", "lunge": "punch", "attack": "fight", "hit": "punch", "strike": "punch", "battle": "fight",
            "chase": "run", "flee": "run", "run_away": "run", "rush": "run", "sneak": "walk", "step": "walk", "approach": "walk",
            "stagger": "fall", "collapse": "fall", "die": "fall", "trip": "fall", "gesture": "talk", "explain": "talk", "speak": "talk",
            "say": "talk", "shout": "talk", "laugh": "cheer", "celebrate": "cheer", "win": "cheer", "victory": "cheer",
            "cry": "sad", "sigh": "sad", "idle": "stand", "wait": "stand", "look": "stand", "watch": "stand", "stare": "stand",
            "sleep": "lie", "rest": "lie", "hide": "crouch", "duck": "crouch", "leap": "jump", "fly": "jump",
            "hop": "jump", "greet": "wave", "hello": "wave", "bye": "wave", "wonder": "think", "ponder": "think", "worry": "sad",
            "rage": "angry", "argue": "angry", "work": "type", "code": "type", "typing": "type", "carry": "hold", "show": "point",
            "present": "point", "celebration": "cheer", "kneel": "crouch", "sit_down": "sit"}
HAND_PROPS = ("phone", "book", "sword", "ball", "cup", "flag")
SCENE_PROPS = ("table", "laptop", "box", "door", "tree", "chair", "screen", "rock", "ladder", "wall")
EFFECTS = ("bulb", "heart", "sweat", "sparkle", "shock", "zzz", "question")
SHOTS = {"wide": 1.0, "medium": 1.14, "close": 1.32}    # план сцены → приближение к главному герою
DRIFT = 0.05                                               # камера за сцену приближается на 5 %: кадр живой с первой секунды
# какой звук у значка над головой
SFX_OF_EFFECT = {"bulb": "ding", "heart": "boop", "sparkle": "sparkle", "shock": "stinger", "question": "boop"}


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def ramp(k, a=0.2):
    """Путь при разгоне и торможении: скорость растёт первые a доли, потом ровная, последние a — тормозит."""
    k = max(0.0, min(1.0, k))
    v = 1 / (1 - a)
    if k < a:
        return v * k * k / (2 * a)
    if k > 1 - a:
        return 1 - v * (1 - k) ** 2 / (2 * a)
    return v * (k - a / 2)


def _strike(f, peak, rest, wind, out):
    """Удар по фазе f (0..1 цикла): стойка → замах (до peak - 0.08) → бросок к peak (резко, у цели тормозит) →
    отдача обратно в стойку (до 0.55). rest, wind, out — позы (словари углов). Возвращает (поза, сила удара 0..1)."""
    w0 = peak - 0.08
    if f < w0:
        return mix(rest, wind, ease(f / w0)), 0.0
    if f < peak:
        q = 1 - (1 - (f - w0) / 0.08) ** 3
        return mix(wind, out, q), max(0.0, 1 - (peak - f) / 0.03)
    if f < 0.55:
        return mix(out, rest, ease((f - peak) / (0.55 - peak))), max(0.0, 1 - (f - peak) / 0.04)
    return dict(rest), 0.0


def mix(a, b, k):
    return {key: a.get(key, BASE[key]) + (b.get(key, BASE[key]) - a.get(key, BASE[key])) * k for key in BASE}


def pose_of(name):
    return dict(BASE, **POSES.get(name, {}))


def action_pose(do, t, dur, speed=None):
    """Поза движения do через t секунд от его начала (dur — длительность). Возвращает (поза, смещение x за шаг 0..1).
    Есть живая запись движения (chloe/mocap.py) — поза из неё; speed — нужная скорость шага (долей роста в секунду)."""
    from . import mocap as MC

    if do in MC.library():
        r = MC.rate_for(do, dur, speed)
        got = MC.pose_at(do, t * r, dur)
        p = dict(BASE)
        p.update(got[0])
        hits, lands = MC.hits_in(do, dur), MC.lands_in(do, dur)
        if any(abs(t - h) < 0.06 for h in hits):
            p["_hit"], p["_hand"] = 1.0, "foot1" if "kick" in do else "hand1"
        if any(0 <= t - x < 0.15 for x in lands):
            p["_land"] = 1.0
        return p, None
    p = pose_of("stand")
    k = t / max(dur, 0.01)
    if do in POSES:
        p = pose_of(do)
        breath = math.sin(t * 2.2) * 1.5                                   # даже в позе живой: дыхание
        p["torso"] += breath * 0.4
        p["sh1"] += breath
        p["sh2"] -= breath
        return p, None
    if do in ("walk", "run"):
        run = do == "run"
        f = t * (2.4 if not run else 3.6) * 2 * math.pi
        amp = 32 if not run else 48
        s = math.sin(f)
        p.update(hip1=amp * s, hip2=-amp * s, kn1=-(8 + 34 * max(0, -s) * (1.6 if run else 1)),
                 kn2=-(8 + 34 * max(0, s) * (1.6 if run else 1)),
                 sh1=-amp * 0.9 * s, el1=25 if not run else 85, sh2=amp * 0.9 * s, el2=25 if not run else 85,
                 torso=4 if not run else 16, dy=0.012 * abs(math.cos(f)) - (0.02 if run else 0))
        return p, ease(k) if not run else ramp(k, 0.18)
    if do == "sneak":                                                   # крадётся: присел, маленькие шаги
        f = t * 1.6 * 2 * math.pi
        s = math.sin(f)
        p.update(hip1=40 + 20 * s, hip2=40 - 20 * s, kn1=-(70 + 20 * max(0, -s)), kn2=-(70 + 20 * max(0, s)), torso=28, dy=-0.1,
                 sh1=60, el1=70, sh2=40, el2=80, head=-10)
        return p, ramp(k, 0.15)
    if do == "crawl":                                                   # ползёт: тело почти горизонтально
        s = math.sin(t * 2.2 * 2 * math.pi)
        # тело наклонено вперёд на 75°: руки и бёдра «вперёд» до наклона — после него смотрят в землю
        p.update(rot=-75, dy=-0.2, sh1=78 + 22 * s, el1=-6, sh2=78 - 22 * s, el2=-6,
                 hip1=72 + 16 * s, kn1=-88, hip2=72 - 16 * s, kn2=-88, head=-35)
        return p, ramp(k, 0.15)
    if do == "climb":                                                   # лезет: руки и ноги по очереди вверх
        s = math.sin(t * 1.8 * 2 * math.pi)
        p.update(sh1=165 - 35 * s, el1=-10, sh2=-(165 + 35 * s), el2=10, hip1=45 + 25 * s, kn1=-80, hip2=45 - 25 * s, kn2=-80,
                 torso=-4, head=-18, dy=0.95 * ease(k) + 0.02 * s)                # поднимается по лестнице
        return p, None
    if do == "fly":                                                     # летит, как супергерой
        p.update(rot=-80, dy=0.25 + 0.03 * math.sin(t * 3), sh1=172, el1=0, sh2=166, el2=0, hip1=-10, kn1=-6, hip2=-16, kn2=-10, head=-25)
        return p, ramp(k, 0.25)
    if do == "throw":                                                   # замах — бросок — проводка руки
        if k < 0.42:
            q = ease(k / 0.42)
            p.update(sh1=40 - 170 * q, el1=40 + 50 * q, torso=-12 * q, hip1=20, hip2=-24, kn1=-10)
        else:
            q = ease((k - 0.42) / 0.25)
            p.update(sh1=-130 + 230 * q, el1=90 - 85 * q, torso=-12 + 32 * q, hip1=20, hip2=-24, kn1=-10, head=6 * q)
        p["_release"] = 1.0 if 0.42 <= k else 0.0
        return p, None
    if do == "jump":
        h = math.sin(math.pi * k)
        crouch = max(0.0, 1 - k / 0.18) if k < 0.18 else (max(0.0, (k - 0.85) / 0.15))
        p["_land"] = 1.0 if k > 0.88 else 0.0
        p.update(dy=0.32 * h - 0.08 * crouch, hip1=50 * h + 30 * crouch, kn1=-90 * h - 50 * crouch, hip2=30 * h + 20 * crouch,
                 kn2=-70 * h - 40 * crouch, sh1=125 * h + 10, sh2=-125 * h - 10, el1=25 * h, el2=-25 * h, head=-10 * h)
        return p, k
    if do == "wave":
        p.update(sh1=150, el1=20 + 25 * math.sin(t * 9), head=-6)
        return p, None
    if do == "talk":
        g = math.sin(t * 3.1)
        p.update(sh1=35 + 25 * g, el1=60 + 20 * math.sin(t * 4.3), sh2=-20 - 10 * g, el2=40, head=4 * math.sin(t * 2.7))
        return p, None
    if do == "dance":
        g = math.sin(t * 6)
        p.update(sh1=110 + 40 * g, el1=40, sh2=-110 + 40 * g, el2=-40, hip1=20 * g, kn1=-30 - 20 * g, hip2=-20 * g,
                 kn2=-30 + 20 * g, torso=8 * g, dy=0.02 * abs(g), head=-6 * g)
        return p, None
    if do in ("punch", "fight"):
        rate, peak = STRIKE[do]
        f = (t * rate) % 1.0
        other = do == "fight" and int(t * rate) % 2 == 1
        a_, b_ = ("2", "1") if other else ("1", "2")
        sign = -1 if other else 1
        rest = dict(p, torso=10, hip1=26, kn1=-20, hip2=-20, kn2=-10, head=4, **{"sh" + a_: 40, "el" + a_: 110 * sign,
                                                                               "sh" + b_: 40, "el" + b_: 110 * -sign if other else 110})
        wind = dict(rest, torso=-2, head=7, **{"sh" + a_: -30, "el" + a_: 130 * sign})      # рука назад, корпус отклонён
        out = dict(rest, torso=24, head=2, **{"sh" + a_: 94, "el" + a_: 0})                  # прямой удар, корпус в удар
        p, hit = _strike(f, peak, rest, wind, out)
        p["_hit"], p["_hand"] = hit, "hand" + a_
        return p, None
    if do == "kick":
        rate, peak = STRIKE["kick"]
        f = (t * rate) % 1.0
        rest = dict(p, sh1=-40, el1=30, sh2=60, el2=40, hip2=-6)
        wind = dict(rest, hip1=60, kn1=-115, torso=-8)                    # колено к груди
        out = dict(rest, hip1=96, kn1=0, torso=-20)                       # нога прямая
        p, hit = _strike(f, peak, rest, wind, out)
        p["_hit"], p["_hand"] = hit, "foot1"
        return p, None
    if do == "fall":
        q = ease(min(1.0, k * 1.6))
        p = mix(pose_of("surprised"), pose_of("lie"), q)
        p["_land"] = 1.0 if 0.6 < k * 1.6 < 1.25 else 0.0                # пыль, когда упал
        return p, None
    return p, None                                                       # idle / неизвестное — просто стоит


# --- рисование ---
def _pt(origin, ang, length, size, facing):
    """Конец отрезка: угол от вертикали вниз, плюс — вперёд."""
    a = math.radians(ang)
    return (origin[0] + facing * math.sin(a) * length * size, origin[1] + math.cos(a) * length * size)


def skeleton(pose, x, ground, size, facing, front=False):
    """Точки суставов на экране: (точки, радиус головы). Земля — под нижней ногой (если не лежит).
    front — лицом к зрителю: правая рука и нога — вправо, левые — влево (углы — «от тела наружу»)."""
    if front:
        return _skeleton_front(pose, x, ground, size)
    hip_y = ground - (SEG["thigh"] + SEG["shin"]) * size - pose["dy"] * size
    hip = (x, hip_y)
    torso_ang = 180 - pose["torso"]          # туловище вверх, наклон вперёд
    neck = _pt(hip, torso_ang, SEG["torso"], size, facing)
    head_c = _pt(neck, torso_ang - pose["head"] * 0.0, SEG["neck"] + SEG["head"], size, facing)
    head_c = (head_c[0] + facing * math.sin(math.radians(pose["head"])) * SEG["head"] * size * 0.5, head_c[1])
    shoulder = _pt(hip, torso_ang, SEG["torso"] * 0.84, size, facing)   # плечи чуть ниже шеи: поднятые руки идут мимо головы
    pts = {"hip": hip, "neck": neck, "head": head_c, "shoulder": shoulder}
    for side in ("1", "2"):
        el = _pt(shoulder, pose["sh" + side] + pose["torso"], SEG["upper"], size, facing)
        hand = _pt(el, pose["sh" + side] + pose["torso"] + pose["el" + side], SEG["fore"], size, facing)
        kn = _pt(hip, pose["hip" + side], SEG["thigh"], size, facing)
        foot = _pt(kn, pose["hip" + side] + pose["kn" + side], SEG["shin"], size, facing)
        pts.update({"el" + side: el, "hand" + side: hand, "kn" + side: kn, "foot" + side: foot})
    if pose["rot"]:                                                     # поворот всего тела вокруг таза (лёжа, падение)
        a = math.radians(-pose["rot"] * facing)
        cx, cy = hip
        for k, (px, py) in list(pts.items()):
            dx, dy = px - cx, py - cy
            pts[k] = (cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a))
    low = max(p[1] for k, p in pts.items() if k != "head")
    if pose["rot"] and (low > ground or (pose["dy"] < 0.1 and low < ground)):   # лежит или ползёт — ровно на земле
        shift = low - ground
        pts = {k: (px, py - shift) for k, (px, py) in pts.items()}
    return pts, SEG["head"] * size


def _skeleton_front(pose, x, ground, size):
    hip_y = ground - (SEG["thigh"] + SEG["shin"]) * size - pose["dy"] * size
    hip = (x, hip_y)
    neck = (x, hip_y - SEG["torso"] * size)
    head = (x + math.sin(math.radians(pose["head"])) * SEG["head"] * size * 0.3, neck[1] - (SEG["neck"] + SEG["head"]) * size)
    shoulder = (x, hip_y - SEG["torso"] * size * 0.84)
    pts = {"hip": hip, "neck": neck, "head": head, "shoulder": shoulder}
    for side, d in (("1", 1), ("2", -1)):
        sh = abs(pose["sh" + side])
        el = _pt(shoulder, sh, SEG["upper"], size, d)
        hand = _pt(el, sh + abs(pose["el" + side]) * 0.8, SEG["fore"], size, d)
        hp = 9 + abs(pose["hip" + side]) * 0.35
        kn = _pt(hip, hp, SEG["thigh"], size, d)
        foot = _pt(kn, hp - abs(pose["kn" + side]) * 0.15, SEG["shin"], size, d)
        pts.update({"el" + side: el, "hand" + side: hand, "kn" + side: kn, "foot" + side: foot})
    return pts, SEG["head"] * size


def _line(c, a, b):
    c.move_to(*a)
    c.line_to(*b)


def draw_face(c, center, r, facing, emotion, talk, ink, filled):
    """Лицо: глаза, брови, рот — по эмоции. На залитой голове — тёмные черты, на полой — цветом линии."""
    import cairo

    cx, cy = center
    col = (0.08, 0.08, 0.08) if filled else ink
    c.set_source_rgb(*col)
    ex = cx + facing * r * 0.28
    eyes = [(ex - r * 0.28, cy - r * 0.12), (ex + r * 0.28, cy - r * 0.12)]
    lw = max(1.5, r * 0.11)
    c.set_line_width(lw)
    if emotion == "happy":
        for x, y in eyes:
            c.arc(x, y + r * 0.05, r * 0.13, math.pi * 1.1, math.pi * 1.9)
            c.stroke()
    else:
        big = 1.6 if emotion == "surprised" else 1.0
        for x, y in eyes:
            c.arc(x, y, r * 0.075 * big, 0, 2 * math.pi)
            c.fill()
    if emotion in ("angry", "sad", "think"):                             # брови
        for i, (x, y) in enumerate(eyes):
            inner = (i == 0) == (facing > 0)
            tilt = {"angry": 1, "sad": -1, "think": 0.5 if i else -0.3}[emotion]
            dy = r * 0.12 * tilt * (1 if inner else -1)
            _line(c, (x - r * 0.16, y - r * 0.3 + (dy if i == 0 else -dy)), (x + r * 0.16, y - r * 0.3 - (dy if i == 0 else -dy)))
            c.stroke()
    mx, my = ex, cy + r * 0.38
    if talk > 0.05 or emotion == "surprised":
        o = r * (0.1 + 0.16 * (talk if emotion != "surprised" else 1.0))
        c.save()
        c.translate(mx, my)
        c.scale(1.0, max(0.25, o / (r * 0.14)))
        c.arc(0, 0, r * 0.14, 0, 2 * math.pi)
        c.restore()
        c.fill()
    elif emotion == "happy":
        c.arc(mx, my - r * 0.12, r * 0.24, math.pi * 0.15, math.pi * 0.85)
        c.stroke()
    elif emotion in ("sad", "angry"):
        c.arc(mx, my + r * 0.2, r * 0.22, math.pi * 1.2, math.pi * 1.8)
        c.stroke()
    else:
        _line(c, (mx - r * 0.16, my), (mx + r * 0.16, my + (r * 0.05 if emotion == "think" else 0)))
        c.stroke()
    c.set_line_cap(cairo.LINE_CAP_ROUND)


def draw_figure(c, pts, r, color, look, emotion, talk, facing, size):
    import cairo

    if look.get("thick"):
        return draw_thick(c, pts, r, color, emotion, talk, facing, size)
    lw = max(2.0, size * 0.022)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_join(cairo.LINE_JOIN_ROUND)

    def limbs():
        for side in ("2", "1"):                                         # дальние руки-ноги — под ближними
            c.move_to(*pts["hip"])
            c.line_to(*pts["kn" + side])
            c.line_to(*pts["foot" + side])
            c.move_to(*pts["shoulder"])
            c.line_to(*pts["el" + side])
            c.line_to(*pts["hand" + side])
        c.move_to(*pts["hip"])
        c.line_to(*pts["neck"])

    for glow_w, alpha in ((lw * 4.5, 0.10), (lw * 2.4, 0.22)) if look["glow"] else ():
        c.set_source_rgba(*color, alpha * look["glow"] * 2)
        c.set_line_width(glow_w)
        limbs()
        c.stroke()
        c.arc(*pts["head"], r, 0, 2 * math.pi)
        c.stroke()
    c.set_source_rgb(*color)
    c.set_line_width(lw)
    limbs()
    c.stroke()
    for side in ("1", "2"):                                              # кисти и стопы — маленькие овалы
        c.arc(*pts["hand" + side], lw * 0.9, 0, 2 * math.pi)
        c.fill()
    c.arc(*pts["head"], r, 0, 2 * math.pi)
    if look["filled_head"]:
        c.set_source_rgb(0.97, 0.97, 0.97) if color != COLORS["white"] else c.set_source_rgb(0.97, 0.97, 0.97)
        c.fill_preserve()
        c.set_source_rgb(*color)
    c.set_line_width(lw)
    c.stroke()
    if look.get("beanie"):                                               # красная шапка (стиль «студия»)
        c.set_source_rgb(0.9, 0.15, 0.15)
        c.arc(pts["head"][0], pts["head"][1] - r * 0.15, r * 1.02, math.pi * 1.05, math.pi * 1.95)
        c.close_path()
        c.fill()
    draw_face(c, pts["head"], r, facing, emotion, talk, color, look["filled_head"])


OUTLINE = (0.04, 0.04, 0.06)


def _bones(c, pts):
    for side in ("2", "1"):
        c.move_to(*pts["hip"])
        c.line_to(*pts["kn" + side])
        c.line_to(*pts["foot" + side])
        c.move_to(*pts["shoulder"])
        c.line_to(*pts["el" + side])
        c.line_to(*pts["hand" + side])
    c.move_to(*pts["hip"])
    c.line_to(*pts["neck"])


def draw_thick(c, pts, r, color, emotion, talk, facing, size):
    """Экшен-рисовка: толстые ровные конечности с тёмной обводкой, залитая голова с обводкой, дальние руки-ноги темнее —
    читается объём и поза даже в быстрой драке."""
    import cairo

    lw = max(3.0, size * 0.058)
    ol = lw * 0.28
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_join(cairo.LINE_JOIN_ROUND)
    far = tuple(v * 0.72 for v in color)
    for side, col in (("2", far), ("1", color)):                      # дальние — темнее и под ближними
        for chain in ((pts["hip"], pts["kn" + side], pts["foot" + side]), (pts["shoulder"], pts["el" + side], pts["hand" + side])):
            for width, cc in ((lw + 2 * ol, OUTLINE), (lw, col)):
                c.set_source_rgb(*cc)
                c.set_line_width(width)
                c.move_to(*chain[0])
                c.line_to(*chain[1])
                c.line_to(*chain[2])
                c.stroke()
        if side == "2":                                               # корпус — между дальними и ближними
            for width, cc in ((lw * 1.15 + 2 * ol, OUTLINE), (lw * 1.15, color)):
                c.set_source_rgb(*cc)
                c.set_line_width(width)
                _line(c, pts["hip"], pts["neck"])
                c.stroke()
    c.arc(*pts["head"], r * 1.05, 0, 2 * math.pi)                     # голова: залитая, с обводкой и бликом
    c.set_source_rgb(*color)
    c.fill_preserve()
    c.set_source_rgb(*OUTLINE)
    c.set_line_width(ol * 2)
    c.stroke()
    c.set_source_rgba(1, 1, 1, 0.28)
    c.arc(pts["head"][0] - r * 0.35, pts["head"][1] - r * 0.4, r * 0.28, 0, 2 * math.pi)
    c.fill()
    draw_face(c, pts["head"], r, facing, emotion, talk, OUTLINE, True)


def draw_smear(c, a, b, width, color):
    """Растяжка быстрого движения: клин от прошлого положения кисти или стопы к нынешнему (как кадр-смаз в анимации)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / d, dx / d
    c.move_to(a[0], a[1])
    c.line_to(b[0] + nx * width / 2, b[1] + ny * width / 2)
    c.line_to(b[0] - nx * width / 2, b[1] - ny * width / 2)
    c.close_path()
    c.set_source_rgba(*color, 0.55)
    c.fill()


def draw_sparks(c, at, k, size, seed, color=(1.0, 0.9, 0.4), scale=1.0):
    """Искры и обломки удара: лучи-вспышка (первые 0,15 с) и кусочки, разлетающиеся с гравитацией (до 0,6 с)."""
    import random

    if k < 0 or k > 0.6:
        return
    rnd = random.Random(seed)
    x, y = at
    if k < 0.15:
        q = k / 0.15
        c.set_line_width(max(2.0, size * 0.012) * scale)
        for i in range(10):
            a = rnd.uniform(0, 2 * math.pi)
            r0, r1 = size * (0.05 + 0.25 * q) * scale, size * (0.12 + 0.4 * q) * rnd.uniform(0.6, 1.0) * scale
            c.set_source_rgba(*color, 1 - q)
            c.move_to(x + math.cos(a) * r0, y + math.sin(a) * r0)
            c.line_to(x + math.cos(a) * r1, y + math.sin(a) * r1)
            c.stroke()
    for i in range(8):                                                  # обломки
        a = rnd.uniform(-math.pi, 0)
        v = size * rnd.uniform(1.2, 2.4) * scale
        px = x + math.cos(a) * v * k
        py = y + math.sin(a) * v * k + 0.5 * size * 5 * k * k
        s_ = size * 0.025 * scale
        c.set_source_rgba(*color, max(0.0, 1 - k / 0.6))
        c.rectangle(px - s_, py - s_, s_ * 2, s_ * 2)
        c.fill()


def draw_hand_prop(c, kind, hand, facing, size, color):
    x, y = hand
    s = size
    c.save()
    c.translate(x, y)
    c.scale(facing, 1)
    if kind == "phone":
        c.set_source_rgb(0.12, 0.12, 0.14)
        _round_rect(c, -s * 0.03, -s * 0.07, s * 0.06, s * 0.11, s * 0.01)
        c.fill()
        c.set_source_rgb(*ACCENT["blue"])
        _round_rect(c, -s * 0.022, -s * 0.06, s * 0.044, s * 0.08, s * 0.006)
        c.fill()
    elif kind == "book":
        c.set_source_rgb(*ACCENT["red"])
        c.rectangle(-s * 0.02, -s * 0.07, s * 0.1, s * 0.08)
        c.fill()
        c.set_source_rgb(1, 1, 1)
        c.rectangle(-s * 0.015, -s * 0.065, s * 0.008, s * 0.07)
        c.fill()
    elif kind == "sword":
        c.set_source_rgb(0.85, 0.88, 0.92)
        c.set_line_width(s * 0.014)
        _line(c, (0, 0), (s * 0.05, -s * 0.3))
        c.stroke()
        c.set_source_rgb(*ACCENT["gold"])
        _line(c, (-s * 0.04, -s * 0.02), (s * 0.05, -s * 0.03))
        c.stroke()
    elif kind == "ball":
        c.set_source_rgb(*ACCENT["red"])
        c.arc(s * 0.03, -s * 0.03, s * 0.045, 0, 2 * math.pi)
        c.fill()
    elif kind == "cup":
        c.set_source_rgb(*ACCENT["gold"])
        c.rectangle(-s * 0.025, -s * 0.07, s * 0.05, s * 0.07)
        c.fill()
    elif kind == "flag":
        c.set_source_rgb(*color)
        c.set_line_width(s * 0.01)
        _line(c, (0, s * 0.05), (0, -s * 0.3))
        c.stroke()
        c.set_source_rgb(*ACCENT["red"])
        c.move_to(0, -s * 0.3)
        c.line_to(s * 0.14, -s * 0.25)
        c.line_to(0, -s * 0.2)
        c.fill()
    c.restore()


def _round_rect(c, x, y, w, h, r):
    c.new_sub_path()
    c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    c.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    c.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    c.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    c.close_path()


def draw_scene_prop(c, kind, x, ground, size, ink, look):
    s = size
    line = ink
    c.set_line_width(max(2.0, s * 0.02))
    c.set_source_rgb(*line)
    if kind == "table":
        c.rectangle(x - s * 0.35, ground - s * 0.45, s * 0.7, s * 0.04)
        c.fill()
        for dx in (-0.3, 0.3):
            _line(c, (x + dx * s, ground - s * 0.42), (x + dx * s, ground))
            c.stroke()
    elif kind == "laptop":
        top = ground - s * 0.45 if look.get("_table_at") == x else ground
        c.set_source_rgb(0.18, 0.18, 0.2)
        c.move_to(x - s * 0.18, top)
        c.line_to(x + s * 0.18, top)
        c.stroke()
        _round_rect(c, x - s * 0.15, top - s * 0.22, s * 0.3, s * 0.2, s * 0.015)
        c.fill()
        c.set_source_rgb(*ACCENT["blue"])
        _round_rect(c, x - s * 0.13, top - s * 0.2, s * 0.26, s * 0.16, s * 0.01)
        c.fill()
    elif kind == "box":
        c.set_source_rgb(*ACCENT["gold"])
        c.rectangle(x - s * 0.2, ground - s * 0.36, s * 0.4, s * 0.36)
        c.fill()
        c.set_source_rgb(*line)
        c.rectangle(x - s * 0.2, ground - s * 0.36, s * 0.4, s * 0.36)
        c.stroke()
    elif kind == "door":
        c.rectangle(x - s * 0.22, ground - s * 1.1, s * 0.44, s * 1.1)
        c.stroke()
        c.arc(x + s * 0.13, ground - s * 0.55, s * 0.025, 0, 2 * math.pi)
        c.fill()
    elif kind == "tree":
        c.set_source_rgb(0.45, 0.3, 0.18)
        c.rectangle(x - s * 0.05, ground - s * 0.6, s * 0.1, s * 0.6)
        c.fill()
        c.set_source_rgb(*COLORS["green"])
        c.arc(x, ground - s * 0.8, s * 0.32, 0, 2 * math.pi)
        c.fill()
    elif kind == "chair":
        _line(c, (x - s * 0.15, ground - s * 0.25), (x + s * 0.15, ground - s * 0.25))
        _line(c, (x - s * 0.15, ground - s * 0.25), (x - s * 0.15, ground))
        _line(c, (x + s * 0.15, ground - s * 0.25), (x + s * 0.15, ground))
        _line(c, (x - s * 0.15, ground - s * 0.25), (x - s * 0.15, ground - s * 0.65))
        c.stroke()
    elif kind == "screen":
        c.set_source_rgb(0.12, 0.12, 0.15)
        _round_rect(c, x - s * 0.5, ground - s * 1.3, s * 1.0, s * 0.62, s * 0.03)
        c.fill()
        c.set_source_rgb(*ACCENT["blue"])
        _round_rect(c, x - s * 0.46, ground - s * 1.26, s * 0.92, s * 0.54, s * 0.02)
        c.fill()
        c.set_source_rgb(0.12, 0.12, 0.15)
        c.rectangle(x - s * 0.03, ground - s * 0.68, s * 0.06, s * 0.68)
        c.fill()
    elif kind == "ladder":
        c.set_source_rgb(0.55, 0.38, 0.22)
        c.set_line_width(max(2.0, s * 0.025))
        _line(c, (x - s * 0.15, ground), (x - s * 0.15, ground - s * 1.6))
        _line(c, (x + s * 0.15, ground), (x + s * 0.15, ground - s * 1.6))
        for i in range(1, 9):
            _line(c, (x - s * 0.15, ground - i * s * 0.18), (x + s * 0.15, ground - i * s * 0.18))
        c.stroke()
    elif kind == "wall":
        c.set_source_rgb(0.62, 0.32, 0.25)
        for row in range(6):
            for col in range(3):
                off = (row % 2) * s * 0.1
                c.rectangle(x - s * 0.3 + col * s * 0.2 + off, ground - (row + 1) * s * 0.12, s * 0.19, s * 0.11)
        c.fill()
    elif kind == "rock":
        c.set_source_rgb(0.5, 0.48, 0.45)
        c.save()
        c.translate(x, ground - s * 0.12)
        c.scale(1.6, 1.0)
        c.arc(0, 0, s * 0.13, math.pi, 2 * math.pi)
        c.restore()
        c.fill()


def draw_effect(c, kind, head, r, t, ink):
    x, y = head[0] + r * 0.9, head[1] - r * 2.0
    bob = math.sin(t * 5) * r * 0.12
    y += bob
    c.set_line_width(max(1.5, r * 0.12))
    if kind == "bulb":
        c.set_source_rgb(*ACCENT["gold"])
        c.arc(x, y, r * 0.5, 0, 2 * math.pi)
        c.fill()
        c.set_source_rgba(*ACCENT["gold"], 0.6)
        for i in range(8):
            a = i * math.pi / 4 + t * 0.6
            _line(c, (x + math.cos(a) * r * 0.7, y + math.sin(a) * r * 0.7), (x + math.cos(a) * r * 0.95, y + math.sin(a) * r * 0.95))
        c.stroke()
    elif kind == "heart":
        c.set_source_rgb(*ACCENT["red"])
        s = r * 0.45 * (1 + 0.12 * math.sin(t * 8))
        c.move_to(x, y + s)
        c.curve_to(x - s * 1.6, y - s * 0.3, x - s * 0.6, y - s * 1.4, x, y - s * 0.5)
        c.curve_to(x + s * 0.6, y - s * 1.4, x + s * 1.6, y - s * 0.3, x, y + s)
        c.fill()
    elif kind == "sweat":
        c.set_source_rgb(*ACCENT["blue"])
        sx, sy = head[0] - r * 1.1, head[1] - r * 0.3 + (t * r * 0.8) % (r * 0.8)
        c.move_to(sx, sy - r * 0.3)
        c.curve_to(sx + r * 0.2, sy, sx + r * 0.15, sy + r * 0.2, sx, sy + r * 0.2)
        c.curve_to(sx - r * 0.15, sy + r * 0.2, sx - r * 0.2, sy, sx, sy - r * 0.3)
        c.fill()
    elif kind == "sparkle":
        c.set_source_rgb(*ACCENT["gold"])
        for i, (dx, dy) in enumerate(((0, 0), (r * 0.9, r * 0.5), (-r * 0.8, r * 0.6))):
            s = r * 0.25 * (0.6 + 0.4 * abs(math.sin(t * 4 + i)))
            px, py = x + dx, y + dy
            c.move_to(px, py - s)
            c.line_to(px + s * 0.3, py)
            c.line_to(px, py + s)
            c.line_to(px - s * 0.3, py)
            c.fill()
            c.move_to(px - s, py)
            c.line_to(px, py + s * 0.3)
            c.line_to(px + s, py)
            c.line_to(px, py - s * 0.3)
            c.fill()
    elif kind == "shock":
        c.set_source_rgb(*ACCENT["red"])
        for i in range(5):
            a = -math.pi / 2 + (i - 2) * 0.45
            _line(c, (head[0] + math.cos(a) * r * 1.4, head[1] + math.sin(a) * r * 1.4),
                  (head[0] + math.cos(a) * r * 2.0, head[1] + math.sin(a) * r * 2.0))
        c.stroke()
    elif kind == "zzz":
        c.set_source_rgb(*ink)
        for i in range(3):
            s = r * (0.25 + 0.1 * i)
            px, py = x + i * r * 0.45, y - i * r * 0.5
            c.move_to(px, py)
            c.line_to(px + s, py)
            c.line_to(px, py + s)
            c.line_to(px + s, py + s)
            c.stroke()
    elif kind == "question":
        c.set_source_rgb(*ACCENT["blue"])
        c.arc(x, y - r * 0.25, r * 0.35, math.pi, math.pi * 2.4)
        c.line_to(x, y + r * 0.35)
        c.stroke()
        c.arc(x, y + r * 0.7, r * 0.09, 0, 2 * math.pi)
        c.fill()


def draw_impact(c, at, size, t):
    """Звёздочка удара: жёлтая вспышка с лучами на кулаке или стопе."""
    x, y = at
    s = size * 0.09
    c.set_source_rgba(*ACCENT["gold"], 0.9)
    c.move_to(x + s, y)
    for i in range(1, 16):
        a = i * math.pi / 8
        rr = s if i % 2 == 0 else s * 0.45
        c.line_to(x + math.cos(a) * rr, y + math.sin(a) * rr)
    c.close_path()
    c.fill()
    c.set_source_rgba(1, 1, 1, 0.9)
    c.arc(x, y, s * 0.25, 0, 2 * math.pi)
    c.fill()


def draw_speed_lines(c, pts, size, back, color):
    """Линии скорости позади бегущего."""
    c.set_source_rgba(*color, 0.45)
    c.set_line_width(max(1.0, size * 0.008))
    hx, hy = pts["hip"]
    for i, dy in enumerate((-0.32, -0.12, 0.08)):
        y = hy + dy * size
        x0 = hx + back * size * (0.18 + 0.05 * i)
        _line(c, (x0, y), (x0 + back * size * (0.35 - 0.06 * i), y))
    c.stroke()


def draw_dust(c, pts, ground, size, t):
    """Облачка пыли у земли: приземлился или упал."""
    c.set_source_rgba(0.6, 0.6, 0.6, 0.35)
    for side in ("1", "2"):
        fx = pts["foot" + side][0]
        for i, dx in enumerate((-0.1, 0.0, 0.1)):
            c.arc(fx + dx * size, ground - size * (0.02 + 0.015 * i), size * (0.035 + 0.01 * ((i + int(t * 10)) % 2)), 0, 2 * math.pi)
            c.fill()


def desktop(c, w, h, t, fake=True):
    """Фон «неон на экране»: тёмный рабочий стол; fake — нарисованные (неживые) окна и иконки для сцен без интерфейса."""
    import cairo

    g = cairo.LinearGradient(0, 0, 0, h)
    g.add_color_stop_rgb(0, 0.05, 0.06, 0.14)
    g.add_color_stop_rgb(1, 0.02, 0.02, 0.05)
    c.set_source(g)
    c.paint()
    c.set_source_rgba(0.3, 0.5, 1.0, 0.06)
    c.set_line_width(1)
    for gx in range(0, w, 48):
        _line(c, (gx, 0), (gx, h))
    for gy in range(0, h, 48):
        _line(c, (0, gy), (w, gy))
    c.stroke()
    for (x, y, ww, hh, col) in ((0.06, 0.1, 0.32, 0.36, "blue"), (0.62, 0.14, 0.3, 0.3, "purple")) if fake else ():
        c.set_source_rgba(*COLORS[col], 0.16)
        _round_rect(c, x * w, y * h, ww * w, hh * h, 10)
        c.fill()
        c.set_source_rgba(*COLORS[col], 0.5)
        c.set_line_width(2)
        _round_rect(c, x * w, y * h, ww * w, hh * h, 10)
        c.stroke()
        c.rectangle(x * w, y * h, ww * w, 0.04 * h)
        c.fill()
    for i in range(4 if fake else 0):
        c.set_source_rgba(*COLORS[("cyan", "yellow", "green", "pink")[i]], 0.7)
        _round_rect(c, 0.015 * w, (0.55 + i * 0.07) * h, 0.03 * w, 0.05 * h, 6)
        c.fill()
    c.set_source_rgba(0.1, 0.12, 0.2, 0.95)
    c.rectangle(0, h * (GROUND + 0.005), w, h)
    c.fill()
    c.set_source_rgba(*COLORS["cyan"], 0.5)
    c.set_line_width(2)
    _line(c, (0, h * (GROUND + 0.005)), (w, h * (GROUND + 0.005)))
    c.stroke()


# --- сцена ---
class Scene:
    """Сцена из описания (JSON мозга), время — доли длины сцены (0..1)."""

    def __init__(self, spec, style="classic_light", size=(1280, 720), secs=6.0, background=None, words=None):
        self.w, self.h = size
        self.secs = max(0.5, float(secs))
        self.look = dict(LOOKS.get(style, LOOKS["classic_light"]))
        self.bg_image = background
        self.fig = FIG * self.h
        self.ground = GROUND * self.h
        ink_name = self.look["ink"]
        self.actors = {}
        for i, a in enumerate((spec or {}).get("actors") or [{"id": "hero"}]):
            aid = str(a.get("id") or "hero{}".format(i))
            col = a.get("color") or "default"
            others = self.look.get("others")
            if others:                                   # у стиля своя короткая палитра: чужой цвет заменяется её цветом
                color = COLORS[col] if col in others else (COLORS[ink_name] if i == 0 else COLORS[others[(i - 1) % len(others)]])
            else:
                color = COLORS.get(col) or (COLORS[ink_name] if i == 0 else COLORS[("red", "blue", "green", "orange")[i % 4]])
            if style == "neon_desktop" and col == "default":
                color = COLORS[("cyan", "red", "yellow", "green")[i % 4]]
            self.actors[aid] = {"id": aid, "color": color, "x": float(a.get("x", 0.3 + 0.4 * i)), "facing": 1 if a.get("facing", "right" if i == 0 else "left") != "left" else -1,
                                "scale": max(0.4, min(1.6, float(a.get("scale", 1.0)))), "emotion": a.get("emotion", "neutral"),
                                "front": a.get("view") == "front" or a.get("facing") == "front", "holds": a.get("holds")}
        self.segs = {k: [] for k in self.actors}
        for s in (spec or {}).get("acting") or []:
            who = s.get("who") if s.get("who") in self.actors else next(iter(self.actors))
            a, b = float(s.get("from", 0)), float(s.get("to", 1))
            if b <= a:
                continue
            do = str(s.get("do") or "stand").lower().strip()
            do = do if do in ACTIONS else SYNONYMS.get(do, "stand")
            if do == "climb" and not any(p_.get("kind") == "ladder" for p_ in (spec or {}).get("props") or []):
                do = "jump"                                               # лезть не по чему — прыжок
            self.segs[who].append(dict(s, t0=a * self.secs, t1=b * self.secs, do=do))
        for k in self.segs:
            self.segs[k].sort(key=lambda s: s["t0"])
        self.props = [p for p in (spec or {}).get("props") or [] if p.get("kind") in SCENE_PROPS]
        tables = [float(p.get("x", 0.5)) for p in self.props if p["kind"] == "table"]
        self.camera = (spec or {}).get("camera") or []
        self.shot = (spec or {}).get("shot") if (spec or {}).get("shot") in SHOTS else None
        self.beat = (spec or {}).get("beat") or ""
        self.words = words or []
        from . import desktop_play as DP

        self.cursor = DP.Cursor((spec or {}).get("cursor"), self.secs, self.w, self.h)
        self.knocks = []
        self._track()
        if self._reach():
            self._track()                                                 # подшагнул к цели — путь пересчитать
        icon_specs = list((spec or {}).get("icons") or [])
        if self.look["bg"] == "desktop" and (self.cursor or (spec or {}).get("windows") or icon_specs):
            mine = {str(i.get("id") or "") for i in icon_specs} | {str(i.get("kind") or "") for i in icon_specs if i.get("kind") == "trash"}
            icon_specs += [d for d in DP.DEFAULT_ICONS if d["id"] not in mine]   # стандартные иконки — всегда, свои — к ним
        self.icons = DP.Icons(icon_specs, self.cursor, self.w, self.h, self.ground)
        self.live_desktop = bool(self.cursor or self.icons.items or (spec or {}).get("windows"))
        for t, aid, s_ in self.hit_times():                               # герой бьёт курсор: курсор сам под кулак и отлетает
            if s_.get("target") == "cursor" and self.cursor:
                x, f = self.where(aid, t)
                size = self.fig * self.actors[aid]["scale"]
                self.cursor.bump(t, x * self.w + f * size * 0.5, self.ground - size * 0.62, f)
        self.cursor.resolve(self._point)                                  # курсор летит к герою, иконке, «Пуску»
        self.trashed = {}
        self.knocks = self._knocks()
        if self.knocks:
            self._track()                                                 # отлёт сдвигает героя — путь пересчитать
            self.cursor.resolve(self._point)                              # а курсор ищет его уже на новом месте
        kicks = [(t, s["target"], self.where(aid, t)[1]) for t, aid, s in self.hit_times() if s.get("target") in self.icons.ids()]
        self.icons.sim(self._boxes, kicks, self.secs)
        if self.icons.hits_on:                                            # иконкой в героя — он отлетает
            for t, victim, d in self.icons.hits_on:
                self.knocks.append({"t": t, "who": victim, "by": "icon", "dir": d, "big": True, "dist": 0.16, "dur": KNOCK_TIME})
            self.knocks.sort(key=lambda k: k["t"])
            self._track()
        self.trashed = self._trash()
        if self.trashed:
            self._track()
        self._items()
        wids = [str(x.get("id") or "w{}".format(i + 1)) for i, x in enumerate((spec or {}).get("windows") or [])]
        breaks = [(s["target"], t, None) for t, aid, s in self.hit_times() if s.get("target") in wids]
        self.windows = DP.Windows((spec or {}).get("windows"), self.cursor, self.w, self.h, breaks)
        self.physics = bool((spec or {}).get("physics", self.look.get("physics")))
        if self.physics and any(k["big"] for k in self.knocks):          # сильный удар — падение по физике
            self._ragdolls()
            self._track()
            self._items()
        self.plan = self._draw_plan((spec or {}).get("draw")) if self.look.get("draw") else {}

    def _items(self):
        """Предметы во времени: кто что держит (до «drop» или передачи), что летит (бросок, передача), что лежит на земле."""
        self.holds = {k: [] for k in self.actors}
        self.flights, self.ground_items = [], []
        a0 = next(iter(self.actors))
        for aid, a in self.actors.items():
            spec_hold = a.get("holds")
            if spec_hold in HAND_PROPS:
                self.holds[aid].append((0.0, spec_hold))
        events = sorted(((s["t0"], aid, s) for aid, segs in self.segs.items() for s in segs), key=lambda e: e[0])
        for t0, aid, s in events:
            d = s["t1"] - s["t0"]
            kind = s.get("prop") if s.get("prop") in HAND_PROPS else None
            if kind and s["do"] not in ("give", "throw"):
                self.holds[aid].append((t0, kind))
            if s.get("drop"):
                self.holds[aid].append((t0, None))
            if s["do"] in ("give", "throw"):
                kind = kind or self.holding(aid, t0) or "ball"
                if not self.holding(aid, t0):
                    self.holds[aid].append((t0, kind))
                to = s.get("target") if s.get("target") in self.actors and s.get("target") != aid else None   # кому
                start = t0 + d * (0.42 if s["do"] == "throw" else 0.35)
                end = s["t1"] - d * (0.0 if s["do"] == "throw" else 0.15)
                self.holds[aid].append((start, None))
                at = s.get("at")
                self.flights.append({"kind": kind, "t0": start, "t1": end, "from": aid, "to": to, "at": at,
                                     "arc": s["do"] == "throw"})
                if to:
                    self.holds[to].append((end, kind))
                else:
                    self.ground_items.append((end, kind, float(at) if at is not None else None, aid))
        for k in self.holds:
            self.holds[k].sort(key=lambda e: e[0])
        del a0

    def _draw_plan(self, draw):
        """Белая доска: когда маркер рисует каждую часть картинки — {ключ: (t0, t1)}. Ключи: "ground", "prop:N", id героя.
        Порядок по смыслу рассказа: место (земля, предметы) → герои; draw от сценариста задаёт свой порядок,
        "word" — начать, когда голос скажет это слово (рисунок идёт за субтитрами)."""
        keys = ["ground"] + ["prop:{}".format(i) for i in range(len(self.props))] + list(self.actors)
        cost = {"ground": 0.5}
        items = []
        for d in draw or []:
            what = str(d.get("what") or "")
            if what not in keys:
                what = next(("prop:{}".format(i) for i, p in enumerate(self.props) if p["kind"] == what and
                             "prop:{}".format(i) not in [x[0] for x in items]), None)
            if what and what not in [x[0] for x in items]:
                items.append((what, d))
        for k in keys:                                                   # что сценарист не назвал — рисуется по порядку
            if k not in [x[0] for x in items]:
                items.insert(0 if k == "ground" else len(items), (k, {}))
        plan, t = {}, 0.15
        budget = self.secs * 0.6                                         # рисунок готов к 60 % сцены — дальше действие
        need = sum(cost.get(k, 1.6 if k in self.actors else 1.2) for k, _ in items) + 0.15 * len(items)
        scale = min(1.0, (budget - 0.15) / max(need, 0.1))
        for k, d in items:
            dur = cost.get(k, 1.6 if k in self.actors else 1.2) * scale
            if d.get("from") is not None:
                t0 = float(d["from"]) * self.secs
                dur = max(0.3, (float(d.get("to", d["from"])) - float(d["from"])) * self.secs) if d.get("to") is not None else dur
            else:
                t0 = self._word_time(d.get("word"), t) if d.get("word") else t
            plan[k] = (t0, min(self.secs, t0 + dur))
            t = max(t, plan[k][1] + 0.15 * scale)
        return plan

    def _prop_x(self, key):
        if key.startswith("prop:"):
            return float(self.props[int(key[5:])].get("x", 0.5))
        return 0.5

    def _word_time(self, word, default):
        """Когда голос начинает слово (по основе: «банан» найдёт «бананы»)."""
        stem = str(word).lower().strip()[:5]
        for a, _b, w in self.words:
            if stem and w.lower().strip(".,!?«»—:;").startswith(stem):
                return a
        return default

    def holding(self, aid, t):
        kind = None
        for when, what in self.holds.get(aid, []):
            if when <= t:
                kind = what
        return kind

    def _track(self):
        """Заранее: где каждый герой в каждый момент (походка двигает его к цели и разворачивает)."""
        from . import mocap as MC

        self.path = {}
        for aid, a in self.actors.items():
            x, facing, pts = a["x"], a["facing"], []
            drops = [{"t0": b, "t1": b, "x": max(0.06, min(0.94, self.cursor.pos(b)[0] / self.w)), "_drop": True}
                     for what, _a, b in self.cursor.grabs if what == aid and b <= self.secs]
            knocks = [{"t0": k["t"], "t1": k["t"] + (0.25 if k.get("blocked") else KNOCK_SLIDE * k["dur"]), "_knock": k}
                      for k in self.knocks if k["who"] == aid and k["dist"] > 0]
            tr = getattr(self, "trashed", {}).get(aid)
            if tr and tr[1] is not None:                                  # выпрыгивает из корзины влево
                bx = self.cursor.pos(tr[0])[0] / self.w
                drops.append({"t0": tr[1], "t1": tr[1] + TRASH_OUT, "x": max(0.05, bx - 0.1), "_pop": True})
            for s in sorted(self.segs[aid] + drops + knocks, key=lambda s: s["t0"]):
                if s.get("_drop"):                  # курсор отпустил героя: дальше он там, где его бросили
                    pts.append((s["t0"], s["t0"], x, s["x"], facing))
                    x = s["x"]
                    continue
                if s.get("_pop"):
                    facing = -1
                    pts.append((s["t0"], s["t1"], x, s["x"], facing))
                    x = s["x"]
                    continue
                if s.get("_knock"):                 # отлетел от удара: дугой и юзом, лицом к обидчику
                    k = s["_knock"]
                    tx = max(0.03, min(0.97, x + k["dir"] * k["dist"]))
                    facing = -k["dir"]
                    if k.get("rag"):                # по физике: где таз — там и герой
                        sim = self._rag[k["rag"]]
                        pts.append((s["t0"], s["t0"] + sim["rest"], x, tx, facing, "rag", k["rag"]))
                    else:
                        pts.append((s["t0"], s["t1"], x, tx, facing, "knock"))
                    x = tx
                    continue
                if s.get("_reach"):                 # подшаг к цели удара — быстро, в начале удара
                    tx, d = s["_reach"]
                    facing = d
                    pts.append((s["t0"], s["t0"] + min(0.3, (s["t1"] - s["t0"]) * 0.3), x, tx, facing))
                    x = tx
                    continue
                if s.get("x") is not None:          # куда сместиться: шаги и бег — походкой, рывок/толчок — скольжением
                    tx = max(0.05, min(0.95, float(s["x"])))
                    if abs(tx - x) > 0.005:
                        facing = 1 if tx > x else -1
                    pts.append((s["t0"], s["t1"], x, tx, facing))
                    s["_speed"] = abs(tx - x) * self.w / (self.fig * a["scale"]) / max(s["t1"] - s["t0"], 0.05)
                    x = tx
                elif s["do"] in MC.library() and not MC.library()[s["do"]].get("loop") and s["do"] not in MC.REPEAT:
                    m = MC.library()[s["do"]]                # сальто, прыжок, падение из записи — тело само сдвигается
                    r = MC.rate_for(s["do"], s["t1"] - s["t0"])
                    end = m["fwd"][-1] * self.fig * a["scale"] / self.w
                    if abs(end) > 0.005:
                        tx = max(0.05, min(0.95, x + facing * end))
                        pts.append((s["t0"], s["t0"] + MC.duration(s["do"]) / r, x, tx, facing, "mocap", s["do"], r))
                        x = tx
                elif s.get("face") in ("left", "right"):
                    facing = 1 if s["face"] == "right" else -1
                    pts.append((s["t0"], s["t0"], x, x, facing))
            self.path[aid] = (a["x"], a["facing"], pts)

    def hit_times(self):
        """Моменты ударов (кулак, нога) — [(время, кто, сегмент)]: на них звук, вспышка, разбитое окно."""
        from . import mocap as MC

        out = []
        for aid, segs in self.segs.items():
            for s in segs:
                if s["do"] in MC.library() and MC.library()[s["do"]]["hits"]:   # живая запись — её моменты ударов
                    for h in MC.hits_in(s["do"], s["t1"] - s["t0"]):
                        out.append((s["t0"] + h, aid, s))
                elif s["do"] in ("punch", "fight", "kick"):
                    rate, peak = STRIKE[s["do"]]
                    n = 0
                    while s["t0"] + (n + peak) / rate < s["t1"]:
                        out.append((s["t0"] + (n + peak) / rate, aid, s))
                        n += 1
        return sorted(out, key=lambda e: e[0])

    def carried(self, aid, t):
        """Курсор держит героя или тот падает после броска: (dx, dy, поворот) смещения головы или None."""
        what, since = self.cursor.holding(t)
        if what == aid:
            cx, cy = self.cursor.pos(t)
            vx, _ = self.cursor.velocity(t)
            by = self.cursor.held_by(what, since)
            return {"head": (cx, cy + self.fig * 0.11), "grip": (cx, cy), "by": by,
                    "swing": max(-35.0, min(35.0, -vx / self.h * 22)), "falling": False}
        for what, b in self.cursor.releases():
            if what == aid and b <= t:
                from . import desktop_play as DP

                if aid in getattr(self, "trashed", {}):
                    return None                                           # не падает — проваливается в корзину
                cx, cy = self.cursor.pos(b)
                head0 = self._drop_head(what, b)
                stand_head = self.ground - self.fig * 0.92
                drop = stand_head - head0
                k = t - b
                fall = DP.fall_time(drop, self.h)
                if k < fall:
                    flip = 180 * (1 - k / fall) if self.cursor.grab_of_release(aid, b) == "foot" else 0.0
                    return {"head": (cx, head0 + 0.5 * DP.GRAVITY * self.h * k * k), "swing": 0.0, "falling": True, "flip": flip}
                return None
        return None

    def _point(self, who, t, part):
        """Куда лететь курсору: голова или нога героя, центр иконки, кнопка «Пуск» (пиксели) или None."""
        if who in self.actors:
            return self.where(who, t)[0] * self.w, self.ground - (self.fig * 0.92 if part == "head" else self.fig * 0.02)
        if who == "start":
            return self.w * 0.02 + self.h * 0.03, self.ground + (self.h - self.ground) * 0.42
        if who in self.icons.ids() or (who == "trash" and self.icons.trash()):
            iid = who if who in self.icons.ids() else self.icons.trash()["id"]
            x, y, _a = self.icons.at(iid, t)
            return x + self.icons.size / 2, y + self.icons.size / 2
        return None

    def _boxes(self, t):
        """Где тела героев (для попадания иконкой): [(id, x0, x1, y0, y1)] в пикселях."""
        out = []
        for aid, a in self.actors.items():
            if self.carried(aid, t) or self.is_hidden(aid, t):
                continue
            x = self.where(aid, t)[0] * self.w
            size = self.fig * a["scale"]
            low = any(s["t0"] <= t < s["t1"] and s["do"] in ("duck", "slide", "roll", "crawl") for s in self.segs[aid])
            out.append((aid, x - size * 0.18, x + size * 0.18, self.ground - size * (0.45 if low else 1.05), self.ground))
        return out

    def _trash(self):
        """Курсор отпустил героя над корзиной — тот проваливается внутрь и выпрыгивает, когда у него следующее движение.
        {id: (когда упал, когда выпрыгнет или None)}."""
        out = {}
        for what, b in self.cursor.releases():
            if what not in self.actors or b > self.secs:
                continue
            r = self.icons.trash_rect(b)
            cx, cy = self.cursor.pos(b)
            if r and r[0] <= cx <= r[0] + r[2] and r[1] - self.fig * 0.3 <= cy <= r[1] + r[3]:
                nxt = [s["t0"] for s in self.segs[what] if s["t0"] > b + 0.4]
                out[what] = (b, min(nxt) if nxt else None)
        return out

    def menu_open(self, t):
        """Насколько выдвинуто меню «Пуск» (0..1): после клика по «Пуску» выезжает и через 1,6 с убирается."""
        k = 0.0
        for tc in self.cursor.clicks_on("start"):
            if tc <= t < tc + 1.9:
                d = t - tc
                k = max(k, ease(d / 0.18) if d < 1.6 else 1 - ease((d - 1.6) / 0.3))
        return k

    def _raw_pts(self, aid, t):
        """Суставы героя в момент t без инерции и украшений — откуда начинается падение по физике."""
        pose, _e, _p, _f, _t = self.state(aid, t)
        x, facing = self.where(aid, t)
        return skeleton(pose, x * self.w, self.ground, self.fig * self.actors[aid]["scale"], facing, False)

    def _ragdolls(self):
        """Сильный удар — тело падает по физике (chloe/ragdoll.py): летит, бьётся о пол, стены и окна, затихает, встаёт."""
        from . import ragdoll as RG

        self._rag = {}
        for k in self.knocks:
            if not k["big"] or k["who"] not in self.actors:
                continue
            aid, t = k["who"], k["t"]
            pts, _r = self._raw_pts(aid, t)
            size = self.fig * self.actors[aid]["scale"]
            walls = [self.windows.rect(wid, t) for wid in self.windows.ids()
                     if not (wid in self.windows.broken and self.windows.broken[wid][0] <= t)]
            sim = RG.simulate(pts, RG.push_for(size, k["dir"], self.h, 1.3 if k.get("by") == "cursor" else 1.0),
                              self.ground, self.w, self.h, walls, size=size)
            k["rag"] = id(k)
            self._rag[id(k)] = sim
            k["dur"] = sim["rest"] + RAG_RISE
            end = RG.sample(sim, sim["rest"])["hip"][0]
            k["dist"] = (end - pts["hip"][0]) / self.w * k["dir"]       # где тело легло — там и встанет

    def is_hidden(self, aid, t):
        tr = getattr(self, "trashed", {}).get(aid)
        return bool(tr and tr[0] + TRASH_IN <= t and (tr[1] is None or t < tr[1]))

    def _drop_head(self, aid, b):
        """Откуда падает герой, когда курсор его отпустил (точка «головы» для расчёта падения): держал за голову — голова
        под курсором; за ногу — тело переворачивается в полёте вокруг таза, и падение считается от ноги у курсора."""
        cy = self.cursor.pos(b)[1]
        return cy + self.fig * (0.03 if self.cursor.grab_of_release(aid, b) == "foot" else 0.11)

    def where(self, aid, t):
        x0, f0, pts = self.path[aid]
        x, facing = x0, f0
        for t0, t1, a, b, f, *kind in pts:
            if t < t0:
                break
            facing = f
            if t >= t1:
                x = b
            else:
                k = (t - t0) / max(t1 - t0, 0.01)
                if kind and kind[0] == "rag":                           # падение по физике — по тазу
                    from . import ragdoll as RG

                    sim = self._rag[kind[1]]
                    hx = RG.sample(sim, t - t0)["hip"][0] / self.w
                    x0 = RG.sample(sim, 0)["hip"][0] / self.w
                    x = a + (hx - x0)
                elif kind and kind[0] == "mocap":                         # сдвиг тела — как в живой записи
                    from . import mocap as MC

                    m = MC.library()[kind[1]]
                    i = min(len(m["fwd"]) - 1, (t - t0) * kind[2] * m["fps"])
                    lo = int(i)
                    hi = min(lo + 1, len(m["fwd"]) - 1)
                    cur = m["fwd"][lo] + (m["fwd"][hi] - m["fwd"][lo]) * (i - lo)
                    k = cur / m["fwd"][-1] if m["fwd"][-1] else k
                    x = a + (b - a) * k
                else:
                    x = a + (b - a) * (1 - (1 - k) ** 2.2 if kind else k)    # отлёт: быстро в начале, юзом до остановки
        return x, facing

    def _reach(self):
        """Удар по герою издалека: нападающий сам подшагивает на длину удара в начале движения. True — что-то поменялось."""
        from . import mocap as MC

        changed = False
        for aid, segs in self.segs.items():
            for s in segs:
                victim = s.get("target")
                lib = MC.library().get(s["do"])
                kicks_far = bool(lib and lib["hits"] and not lib.get("loop") and s["do"] not in MC.REPEAT)
                if (s["do"] not in STRIKE and not kicks_far) or victim not in self.actors or victim == aid or \
                        s.get("x") is not None or s.get("_reach"):
                    continue
                ax, _ = self.where(aid, s["t0"])
                vx, _ = self.where(victim, s["t0"])
                reach = REACH * self.h / self.w * (1.25 if "kick" in s["do"] else 1.0)
                if kicks_far:                                              # тело само летит вперёд к удару — учесть
                    r = MC.rate_for(s["do"], s["t1"] - s["t0"])
                    reach += MC.fwd_at(s["do"], lib["hits"][0]) * self.fig * self.actors[aid]["scale"] / self.w
                d = 1 if vx >= ax else -1
                tx = vx - d * reach
                if abs(tx - ax) > 0.015:
                    s["_reach"] = (tx, d)
                    changed = True
        return changed

    def _knocks(self):
        """Удары по героям (punch/kick/fight с "target": id героя): последний удар серии отбрасывает, остальные — вздрагивание."""
        out = []
        series = {}
        for t, aid, s in self.hit_times():
            victim = s.get("target")
            if victim in self.actors and victim != aid:
                series.setdefault(id(s), []).append((t, aid, s, victim))
        for hits in series.values():
            hits = [h for h in hits if not self.dodging(h[3], h[0])]       # увернулся — удар мимо
            for i, (t, aid, s, victim) in enumerate(hits):
                ax, af = self.where(aid, t)
                vx, _ = self.where(victim, t)
                d = 1 if (vx - ax) > 0.01 else -1 if (vx - ax) < -0.01 else af
                if self.blocking(victim, t, ax):                          # в стойке защиты лицом к обидчику — блок
                    out.append({"t": t, "who": victim, "by": aid, "dir": d, "big": False, "blocked": True, "dist": 0.025,
                                "dur": 0.0})
                    continue
                last = i == len(hits) - 1
                power = 1.3 if s["do"] == "kick" else 1.0
                out.append({"t": t, "who": victim, "by": aid, "dir": d, "big": last, "dist": 0.2 * power if last else 0.0,
                            "dur": KNOCK_TIME * (power if last else 0.0)})
        for t, victim, d in self.cursor.hits():                           # удар курсором — сразу отлёт
            if victim in self.actors and not self.dodging(victim, t):
                out.append({"t": t, "who": victim, "by": "cursor", "dir": d, "big": True, "dist": 0.22, "dur": KNOCK_TIME * 1.1})
        return sorted(out, key=lambda k: k["t"])

    def _live_move(self, aid, t):
        from . import mocap as MC

        return any(s["t0"] <= t < s["t1"] and s["do"] in MC.library() for s in self.segs.get(aid, []))

    def blocking(self, aid, t, from_x=None):
        """Герой в стойке защиты (guard) и обидчик перед ним — удар в блок."""
        from . import mocap as MC

        if not any(s["t0"] <= t < s["t1"] and s["do"] in MC.BLOCK for s in self.segs.get(aid, [])):
            return False
        if from_x is None:
            return True
        x, facing = self.where(aid, t)
        return (from_x - x) * facing >= -0.01

    def dodging(self, aid, t):
        """Герой в момент t уворачивается (пригнулся, подкат, кувырок, сальто, прыжок) — удар проходит мимо."""
        from . import mocap as MC

        return any(s["t0"] <= t < s["t1"] and s["do"] in MC.DODGE for s in self.segs.get(aid, []))

    def knocked(self, aid, t):
        """Что сейчас с героем после удара: ("flinch", k) — вздрогнул, ("fly"|"slide"|"rise", k) — отлетел; иначе None."""
        cur = None
        for k in self.knocks:
            if k["who"] == aid and k["t"] <= t:
                cur = k
        if not cur:
            return None
        dt = t - cur["t"]
        if cur.get("blocked"):
            return ("block", dt / 0.3, cur) if dt < 0.3 else None
        if cur.get("rag"):
            rest = self._rag[cur["rag"]]["rest"]
            if dt < rest:
                return ("ragdoll", dt, cur)
            return ("rise_rag", (dt - rest) / RAG_RISE, cur) if dt < rest + RAG_RISE else None
        if not cur["big"]:
            return ("flinch", dt / 0.22, cur) if dt < 0.22 else None
        q = dt / cur["dur"]
        if q >= 1:
            return None
        if q < KNOCK_FLY:
            return ("fly", q / KNOCK_FLY, cur)
        if q < KNOCK_SLIDE:
            return ("slide", (q - KNOCK_FLY) / (KNOCK_SLIDE - KNOCK_FLY), cur)
        return ("rise", (q - KNOCK_SLIDE) / (1 - KNOCK_SLIDE), cur)

    def state(self, aid, t):
        """(поза, эмоция, предмет, значок, говорит) героя в момент t, с плавным переходом между движениями."""
        segs = self.segs[aid]
        cur, prev = None, None
        for s in segs:
            if s["t0"] <= t < s["t1"]:
                cur = s
            elif s["t1"] <= t:
                prev = s
        a = self.actors[aid]

        def pose_at(seg, tt):
            if not seg:
                p, _ = action_pose("stand", tt, 1.0)
                return p
            p, _ = action_pose(seg["do"], tt - seg["t0"], seg["t1"] - seg["t0"], seg.get("_speed"))
            return p

        self._front = a["front"]
        if cur is None:
            hold = prev if prev and prev["do"] in POSES and prev["do"] not in ("cheer", "surprised") else None
            if hold and (hold.get("view") == "front" or hold["do"] in FRONT):
                self._front = hold.get("view") != "side"
            base = pose_at(hold, t) if hold else pose_at(None, t)
            src = pose_at(prev, prev["t1"] - 0.001) if prev else base
            k = ease((t - prev["t1"]) / BLEND) if prev else 1.0
            pose = mix(src, base, k)
            emo = (prev or {}).get("emotion") or (EMOTION_OF.get(prev["do"]) if prev and hold else None) or a["emotion"]
            return pose, emo, self.holding(aid, t), None, 0.0
        pose = pose_at(cur, t)
        if t - cur["t0"] < BLEND:
            before = [s for s in segs if s["t1"] <= cur["t0"] + 0.001]
            src = pose_at(before[-1], cur["t0"] - 0.001) if before else pose_at(None, t)
            pose = mix(src, pose, ease((t - cur["t0"]) / BLEND))
        if cur.get("view") in ("front", "side"):
            self._front = cur["view"] == "front"
        elif cur["do"] in FRONT:
            self._front = True
        elif cur["do"] in MOVING or cur["do"] in ("punch", "fight", "kick", "throw", "give", "push", "hug", "catch", "fall", "lie"):
            self._front = False
        emo = cur.get("emotion") or EMOTION_OF.get(cur["do"]) or a["emotion"]
        talk = 0.0
        if cur["do"] == "talk" or cur.get("talk"):
            talk = 0.5 + 0.5 * math.sin(t * 17) if self._speaking(t) or not self.words else 0.0
        return pose, emo, self.holding(aid, t), cur.get("effect") if cur.get("effect") in EFFECTS else None, talk

    def sound_events(self):
        """Где в сцене звучать: шаги, удары, падения, прыжки, броски, значки — с точным временем пика и панорамой по x.
        Время берётся из тех же формул (или живых записей), что движут скелет: удар звучит на кадре, где рука дальше всего."""
        from . import mocap as MC

        ev = []

        def add(t, kind, aid, **kw):
            if 0 <= t <= self.secs:
                ev.append(dict(kw, t=round(t, 4), kind=kind, pan=(self.where(aid, t)[0] - 0.5) * 2, who=aid))

        for aid, segs in self.segs.items():
            for s in segs:
                t0, t1, do = s["t0"], s["t1"], s["do"]
                d = t1 - t0
                if do in ("walk", "run", "sneak") and s.get("x") is not None:
                    rate = {"walk": 2.4, "run": 3.6, "sneak": 1.6}[do]
                    if do in MC.library():                              # живая запись: два шага за цикл
                        rate = MC.rate_for(do, d, s.get("_speed")) / MC.duration(do)
                    n = 1
                    while t0 + n / (2 * rate) < t1:
                        add(t0 + n / (2 * rate), "step", aid, gain_db={"run": 3, "sneak": -8}.get(do, 0), args={"weight": 1.3 if do == "run" else 1})
                        n += 1
                    if do == "run":
                        add(t0 + min(0.3, d * 0.3), "whoosh", aid, gain_db=-4)
                elif do in ("crawl", "climb"):
                    rate = 2.2 if do == "crawl" else 1.8
                    n = 1
                    while t0 + n / (2 * rate) < t1:
                        add(t0 + n / (2 * rate), "flutter" if do == "crawl" else "tap", aid, args={} if do == "crawl" else {"pitch": 420})
                        n += 1
                elif do in ("punch", "fight", "kick", "jumpkick", "spinkick"):
                    for t, _a, sg in self.hit_times():
                        if sg is s:
                            add(t - 0.05, "swish", aid, gain_db=-4 if "kick" in do else -6)
                            add(t, "punch", aid, args={"size": {"fight": 0.9, "punch": 1.0}.get(do, 1.2)})
                    if do in ("jumpkick", "spinkick"):
                        add(t0 + 0.2, "whoosh", aid, args={"dur": 0.4}, gain_db=-3)
                        for x in MC.lands_in(do, d):
                            add(t0 + x, "thud", aid, gain_db=-6, args={"size": 0.7})
                elif do in MC.library() and do not in ("walk", "run", "jump"):   # акробатика и падения из записей
                    add(t0 + min(0.4, d * 0.2), "whoosh", aid, args={"dur": 0.45}, gain_db=-2)
                    for x in MC.lands_in(do, d):
                        add(t0 + x, "thud", aid, gain_db=-3 if do in ("faceplant", "slip", "rugpull") else -6)
                elif do == "fall":
                    add(t0 + d * 0.35, "whoosh", aid, args={"dur": min(0.5, d * 0.6), "heavy": True})
                    add(t0 + d * 0.625, "thud", aid)
                elif do == "jump":
                    lands = MC.lands_in("jump", d) if "jump" in MC.library() else [d * 0.97]
                    add(t0 + (lands[0] * 0.55 if lands else d * 0.3), "whoosh", aid, gain_db=-3, args={"dur": min(0.4, d * 0.5)})
                    for x in lands[:1]:
                        add(t0 + x, "thud", aid, gain_db=-7, args={"size": 0.7})
                elif do == "fly":
                    add(t0 + min(0.35, d * 0.4), "whoosh", aid, args={"dur": 0.7, "heavy": True})
                elif do == "throw":
                    add(t0 + d * 0.48, "swish", aid)
                elif do in ("hug", "catch"):
                    add(t0 + min(0.25, d * 0.3), "flutter", aid, gain_db=4)
                elif do == "dance":
                    add(t0 + 0.05, "sparkle", aid, gain_db=-6)
                if s.get("effect") in SFX_OF_EFFECT:
                    add(t0 + 0.12, SFX_OF_EFFECT[s["effect"]], aid)
                if do in ("surprised",) and not s.get("effect"):
                    add(t0 + 0.05, "boop", aid, gain_db=-3)
        if self.cursor:                                                  # интерфейс: клики, стекло, уроненный герой
            from . import desktop_play as DP

            first = next(iter(self.actors))
            for tp in self.cursor.presses():
                if 0 <= tp <= self.secs:
                    ev.append({"t": round(tp, 4), "kind": "click", "who": first, "pan": (self.cursor.pos(tp)[0] / self.w - 0.5) * 2})
            for what, b in self.cursor.releases():
                if what in self.actors and b <= self.secs:
                    land = b + DP.fall_time((self.ground - self.fig * 0.92) - self._drop_head(what, b), self.h)
                    add(b + 0.05, "whoosh", what, args={"dur": 0.4}, gain_db=-4)
                    add(land, "thud", what)
        for what, a_, b in self.cursor.grabs:                             # иконки: бросок, стук об пол, попадание
            if what in self.icons.flights and b <= self.secs:
                ev.append({"t": round(b + 0.08, 4), "kind": "whoosh", "who": next(iter(self.actors)), "pan": 0.0, "args": {"dur": 0.35}})
        for tb, iid in self.icons.bounces:
            if tb <= self.secs:
                ev.append({"t": round(tb, 4), "kind": "tap", "who": next(iter(self.actors)), "pan": 0.0, "args": {"pitch": 520}})
        for ht, victim, _d in self.icons.hits_on:
            add(ht, "punch", victim, args={"size": 0.8})
        for tc in self.cursor.clicks_on("start"):
            ev.append({"t": round(tc + 0.08, 4), "kind": "pop", "who": next(iter(self.actors)), "pan": -0.9})
        for td in self.cursor.dives():                                    # курсор нырнул в корзину
            ev.append({"t": round(td, 4), "kind": "tap", "who": next(iter(self.actors)), "pan": 0.8, "args": {"pitch": 300}})
            ev.append({"t": round(td + 0.05, 4), "kind": "boop", "who": next(iter(self.actors)), "pan": 0.8})
        for aid, (tin, tout) in self.trashed.items():                     # корзина: провалился, выпрыгнул
            add(tin + TRASH_IN * 0.8, "thud", aid, gain_db=-6, args={"size": 0.6})
            add(tin + TRASH_IN * 0.85, "tap", aid, args={"pitch": 260})
            if tout is not None:
                add(tout + 0.05, "pop", aid)
                add(tout + 0.1, "whoosh", aid, args={"dur": 0.3}, gain_db=-4)
        for ht, victim, _d in self.cursor.hits():                         # курсор врезался в героя
            if victim in self.actors:
                add(ht - 0.06, "swish", victim, gain_db=-3)
                add(ht, "punch", victim, args={"size": 0.85})
        for k in self.knocks:                                             # отлёт: свист полёта, удар о пол, шорох юзом
            if k.get("blocked"):                                          # блок: глухой стук и звон
                add(k["t"] + 0.005, "thud", k["who"], gain_db=-4, args={"size": 0.5})
                add(k["t"] + 0.01, "tap", k["who"], args={"pitch": 240})
            if k.get("rag"):                                              # физика: звук там, где тело правда ударилось
                add(k["t"] + 0.1, "whoosh", k["who"], args={"dur": 0.35}, gain_db=-3)
                for ht, what, hx, force in self._rag[k["rag"]]["hits"][:6]:
                    gain = max(-12.0, min(0.0, (force - 1.5) * 5))
                    ev.append({"t": round(k["t"] + ht, 4), "kind": "punch" if what == "window" else "thud", "who": k["who"],
                               "pan": (hx / self.w - 0.5) * 2, "gain_db": gain - (3 if what == "window" else 0),
                               **({"args": {"size": 0.7}} if what == "window" else {})})
                continue
            if k["big"]:
                add(k["t"] + 0.12, "whoosh", k["who"], args={"dur": 0.35}, gain_db=-3)
                add(k["t"] + k["dur"] * KNOCK_FLY, "thud", k["who"])
                n = 0
                while n < 4:
                    add(k["t"] + k["dur"] * (KNOCK_FLY + 0.04 + n * 0.055), "flutter", k["who"], gain_db=6 - 3 * n)
                    n += 1
        for wid, (tb, _) in self.windows.broken.items():
            x, _y, ww, _hh = self.windows.rect(wid, tb)
            ev.append({"t": round(tb, 4), "kind": "shatter", "who": next(iter(self.actors)), "pan": ((x + ww / 2) / self.w - 0.5) * 2})
        for key, (t0, t1) in self.plan.items():                        # белая доска: скрип маркера, пока он рисует
            if t1 - t0 > 0.2:
                aid = key if key in self.actors else next(iter(self.actors))
                ev.append({"t": round(t0, 4), "kind": "scribble", "who": aid, "args": {"dur": round(t1 - t0, 3)},
                           "pan": ((self.where(key, t0)[0] if key in self.actors else self._prop_x(key)) - 0.5) * 2})
        for f in self.flights:
            aid = f["to"] or f["from"]
            if f["to"]:
                add(f["t1"], "pop", aid)                        # поймал
            else:
                add(f["t1"], "thud", f["from"], gain_db=-8, args={"size": 0.6})   # упало на землю
        return sorted(ev, key=lambda e: e["t"])

    def _speaking(self, t):
        return any(a <= t <= b for a, b, _w in self.words)

    def cam(self, t):
        """Приближение и тряска камеры: (масштаб, центр x, центр y, сдвиг).
        План сцены (shot) задаёт исходное приближение к главному герою; камера всегда чуть плывёт вперёд —
        движется уже на первом кадре и ещё движется на стыке (кроме тихих сцен и финала: там держится)."""
        zoom, fx, fy = 1.0, self.w / 2, self.h / 2
        if self.look.get("camera") == "follow":
            return self._follow(t)
        if self.shot and not self.look.get("still") and not getattr(self, "live_desktop", False):   # доска и живой стол стоят
            base = SHOTS[self.shot]
            drift = 0.0 if self.beat in ("quiet", "ending") else DRIFT * t / self.secs
            zoom = base * (1 + drift)
            if base > 1.0 and self.actors:
                x, _ = self.where(next(iter(self.actors)), t)
                k = (base - 1) / (SHOTS["close"] - 1)
                fx = fx + (x * self.w - fx) * k
                fy = fy + ((self.ground - self.fig * 0.55) - fy) * k
        for cm in self.camera if not getattr(self, "live_desktop", False) else ():   # живой стол: камера стоит
            a, b = float(cm.get("from", 0)) * self.secs, float(cm.get("to", 1)) * self.secs
            if a <= t <= b + 0.4:
                k = ease((t - a) / 0.6) * (1 - ease((t - b) / 0.4))
                z = max(1.0, min(2.0, float(cm.get("zoom", 1.3))))
                zoom = max(zoom, 1 + (z - 1) * k)
                on = cm.get("on")
                if on in self.actors:
                    x, _ = self.where(on, t)
                    fx = fx + (x * self.w - fx) * k
                    fy = fy + ((self.ground - self.fig * 0.55) - fy) * k
        shake = 0.0
        for aid, segs in self.segs.items():
            for s in segs:
                if s["do"] in ("punch", "fight", "kick", "fall") and s["t0"] <= t <= s["t1"] and s.get("shake", True):
                    shake = max(shake, 3.0)
        return zoom, fx, fy, shake

    HITSTOP = 0.12                                                       # секунд «стоп-кадра» на сильном ударе

    def stops(self):
        """Моменты паузы на ударе (сильные удары, не больше четырёх за сцену)."""
        if not self.look.get("hitstop"):
            return []
        return sorted(k["t"] for k in self.knocks if k["big"])[:4]

    def scene_time(self, tv):
        """Время ролика → время сцены: на сильном ударе сцена на миг замирает (пауза на ударе)."""
        for s0 in self.stops():
            if tv > s0 + self.HITSTOP:
                tv -= self.HITSTOP
            elif tv > s0:
                tv = s0
        return tv

    def video_time(self, ts):
        """Время сцены → время ролика (для звуков: после паузы они сдвигаются вместе с картинкой)."""
        return ts + sum(self.HITSTOP for s0 in self.stops() if ts > s0)

    def _follow(self, t):
        """Камера сама следит за дракой: держит всех героев в кадре (плавно — среднее за 0,6 с), приближается, когда они
        рядом; на сильном ударе — рывок вперёд и тряска. Кадр не выходит за края экрана."""
        w, h = self.w, self.h
        xs, ys = [], []
        for k in range(7):
            tt = max(0.0, t - 0.6 + k * 0.1)
            for aid, a in self.actors.items():
                if self.is_hidden(aid, tt):
                    continue
                hang = self.carried(aid, tt)
                x = hang["head"][0] if hang else self.where(aid, tt)[0] * w
                size = self.fig * a["scale"]
                xs += [x - size * 0.45, x + size * 0.45]
                ys += [(hang["head"][1] if hang else self.ground - size * 1.1), self.ground]
        if not xs:
            return 1.0, w / 2, h / 2, 0.0
        bw, bh = max(xs) - min(xs), max(ys) - min(ys)
        zoom = max(1.0, min(1.5, min(0.62 * w / max(bw, 1.0), 0.75 * h / max(bh, 1.0))))
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2 - h * 0.04
        shake = 0.0
        for k in self.knocks:                                            # сильный удар: рывок камеры и тряска
            d = t - k["t"]
            if 0 <= d < 0.45 and (k["big"] or k.get("blocked")):
                q = 1 - d / 0.45
                zoom *= 1 + (0.12 if k["big"] else 0.04) * q
                shake = max(shake, h * (0.012 if k["big"] else 0.005) * q)
        half_w, half_h = w / 2 / zoom, h / 2 / zoom
        cx = max(half_w, min(w - half_w, cx))
        cy = max(half_h, min(h - half_h, cy))
        return zoom, cx, cy, shake

    def _paint_bg(self, c, t):
        w, h = self.w, self.h
        bg = self.look["bg"]
        if self.bg_image is not None:
            c.save()
            c.scale(w / self.bg_image.get_width(), h / self.bg_image.get_height())
            c.set_source_surface(self.bg_image, 0, 0)
            c.paint()
            c.restore()
        elif bg == "desktop":
            desktop(c, w, h, t, fake=not self.live_desktop)
        else:
            c.set_source_rgb(*bg)
            c.paint()

    def render(self, c, t, cairo):
        w, h = self.w, self.h
        c.identity_matrix()
        bg = self.look["bg"]
        follow = self.look.get("camera") == "follow"
        if not follow:
            self._paint_bg(c, t)
        zoom, fx, fy, shake = self.cam(t)
        sx = math.sin(t * 61) * shake
        sy = math.cos(t * 47) * shake
        if follow:                                                      # камера следит: фон приближается вместе со всеми
            c.set_source_rgb(0, 0, 0)
            c.paint()
        c.translate(w / 2 + sx, h / 2 + sy)
        c.scale(zoom, zoom)
        c.translate(-fx, -fy)
        if follow:
            self._paint_bg(c, t)
        ink = COLORS[self.look["ink"]]
        pens = []                                                        # где сейчас маркер (белая доска)

        def part(key, draw, strokes=None):
            """Нарисовать часть картинки; на белой доске — только ту долю, что маркер уже провёл."""
            t0, t1 = self.plan.get(key, (-1.0, -1.0))
            if t >= t1:
                draw(c)
            elif t >= t0:
                tip = reveal(c, cairo, draw, (t - t0) / max(t1 - t0, 0.01), strokes, self.fig)
                if tip:
                    pens.append(tip)

        if self.look["ground"] and self.bg_image is None:
            def ground(cc):
                cc.set_source_rgb(*self.look["ground"])
                cc.set_line_width(max(1.5, h * 0.003))
                _line(cc, (-w, self.ground), (2 * w, self.ground))
                cc.stroke()
            part("ground", ground, [[(-w * 0.0, self.ground), (w * 1.0, self.ground)]])
        tables = [float(p.get("x", 0.5)) * w for p in self.props if p["kind"] == "table"]
        for i, p in enumerate(self.props):
            px = float(p.get("x", 0.5)) * w
            look = dict(self.look, _table_at=px if any(abs(px - tx) < self.fig * 0.3 for tx in tables) else None)
            part("prop:{}".format(i), lambda cc, p=p, px=px, look=look: draw_scene_prop(self._pen(cc), p["kind"], px, self.ground, self.fig, ink, look))
        for when, kind, at, who in self.ground_items:                    # брошенное без адресата — лежит на земле
            if t >= when:
                gx = (at if at is not None else self.where(who, when)[0] + 0.25 * self.where(who, when)[1]) * w
                draw_hand_prop(self._pen(c), kind, (gx, self.ground - self.fig * 0.02), 1, self.fig, ink)
        if self.live_desktop and bg == "desktop":
            from . import desktop_play as DP

            top = self.ground + h * 0.005
            DP.draw_taskbar(c, w, h, top, t, active=self.menu_open(t) > 0)
            inside = any(self.is_hidden(a, t) or (tr[0] <= t < tr[0] + TRASH_IN) or (tr[1] is not None and tr[1] <= t < tr[1] + 0.3)
                         for a, tr in self.trashed.items()) or any(0 <= t - td < 0.8 for td in self.cursor.dives())
            self.icons.draw(c, t, COLORS, wobble=0.12 if inside else 0.0)
        self.windows.draw(c, t, COLORS)
        if self.live_desktop and bg == "desktop" and self.menu_open(t) > 0:
            DP.draw_taskbar(c, w, h, self.ground + h * 0.005, t, menu=self.menu_open(t), only_menu=True)
        hands = {}
        for aid in sorted(self.actors, key=lambda k: self.actors[k]["scale"]):
            t0, t1 = self.plan.get(aid, (-1.0, -1.0))
            if t < t0 or self.is_hidden(aid, t):
                continue
            tt = t1 if t < t1 else t                                    # пока маркер рисует героя — он замер
            hands[aid], pts, r = self._actor(c, aid, tt, ink, measure=True)
            if t < t1:
                bones = [_circle(pts["head"], r)] + [[pts["hip"], pts["neck"]]] + \
                        [[pts["shoulder"], pts["el" + s_], pts["hand" + s_]] for s_ in ("1", "2")] + \
                        [[pts["hip"], pts["kn" + s_], pts["foot" + s_]] for s_ in ("1", "2")]
                part(aid, lambda cc, aid=aid, tt=tt: self._actor(cc, aid, tt, ink), bones)
            else:
                self._actor(c, aid, t, ink)
        for f in self.flights:                                           # предмет в полёте: бросок — дугой, передача — из рук в руки
            if f["t0"] <= t <= f["t1"]:
                k = (t - f["t0"]) / max(f["t1"] - f["t0"], 0.01)
                sx_, sy_ = hands.get(f["from"], (w / 2, self.ground))
                if f["to"] in hands:
                    ex_, ey_ = hands[f["to"]]
                else:
                    ex_ = (f["at"] if f["at"] is not None else self.where(f["from"], f["t0"])[0] + 0.25 * self.where(f["from"], f["t0"])[1]) * w
                    ey_ = self.ground - self.fig * 0.02
                px_ = sx_ + (ex_ - sx_) * ease(k) if not f["arc"] else sx_ + (ex_ - sx_) * k
                py_ = sy_ + (ey_ - sy_) * (ease(k) if not f["arc"] else k) - (math.sin(math.pi * k) * self.fig * 0.45 if f["arc"] else 0)
                draw_hand_prop(self._pen(c), f["kind"], (px_, py_), 1, self.fig, ink)
        self.windows.draw_shards(c, t, COLORS, self.ground)
        if self.cursor and not self.cursor.gone(t):
            from . import desktop_play as DP

            pressed = [t - p for p in self.cursor.presses() if 0 <= t - p]
            DP.draw_cursor(c, self.cursor.pos(t), self.h, min(pressed) if pressed else None, self.cursor.holding(t)[0] is not None,
                           self.cursor.mood(t), self.cursor.velocity(t) if not self.cursor.bumped(t)[2] else (0.0, 0.0), t,
                           self.cursor.bumped(t)[2])
        for tip in pens:                                                 # маркер — поверх всего, в координатах экрана
            draw_marker(c, tip, self.h, t)
        if self.look.get("impact"):                                      # искры и обломки на каждом ударе по герою
            for k in self.knocks:
                d = t - k["t"]
                if 0 <= d <= 0.6 and k["who"] in self.actors:
                    vx = self.where(k["who"], k["t"])[0] * w
                    size = self.fig * self.actors[k["who"]]["scale"]
                    at = (vx - k["dir"] * size * 0.12, self.ground - size * 0.72)
                    draw_sparks(c, at, d, size, int(k["t"] * 1000), (0.6, 0.9, 1.0) if k.get("blocked") else (1.0, 0.85, 0.3),
                                0.6 if k.get("blocked") else 1.0)
        if self.look.get("flash"):                                       # вспышка на кадре сильного удара и разбитого стекла
            hits = [ht for ht, _a, _s in self.hit_times()] + [tb for tb, _ in self.windows.broken.values()] + \
                [ht for ht, _v, _d in self.cursor.hits()]
            near = [t - ht for ht in hits if 0 <= t - ht < 0.08]
            if near:
                c.save()
                c.identity_matrix()
                c.set_source_rgba(1, 1, 1, 0.22 * (1 - min(near) / 0.08))
                c.paint()
                c.restore()
        if self.look.get("impact") and any(0 <= t - k["t"] < 1.5 / FPS for k in self.knocks if k["big"]):
            c.save()                                                     # кадр-негатив на сильном ударе
            c.identity_matrix()
            c.set_operator(cairo.OPERATOR_DIFFERENCE)
            c.set_source_rgb(1, 1, 1)
            c.paint()
            c.restore()

    def landed(self, aid, t):
        """Сколько секунд назад герой приземлился после того, как курсор его уронил (None — не падал или давно)."""
        from . import desktop_play as DP

        for what, b in self.cursor.releases():
            if what == aid and b <= t and aid not in getattr(self, "trashed", {}):
                fall = DP.fall_time((self.ground - self.fig * 0.92) - self._drop_head(aid, b), self.h)
                if b + fall <= t < b + fall + 1.0:
                    return t - b - fall
        return None

    def _smooth(self, aid, t, target):
        """Суставы догоняют позу пружиной (инерция, запаздывание, лёгкий довод). Кадры идут по порядку — состояние
        копится; запрос назад во времени (след движения) берёт уже посчитанный кадр."""
        sim = self.__dict__.setdefault("_springs", {})
        key = round(t, 4)
        st = sim.get(aid)
        if st and key in st["seen"]:
            out = dict(target)
            out.update(st["seen"][key])
            return out
        if not st or t < st["t"]:
            if st and t < st["t"]:
                return target                                            # старый кадр, которого не видели — как есть
            st = sim[aid] = {"t": t, "x": {k: float(target.get(k, 0)) for k in BASE}, "v": {k: 0.0 for k in BASE}, "seen": {}}
        dt_all = t - st["t"]
        steps = max(1, int(dt_all / 0.005))
        dt = dt_all / steps if dt_all > 0 else 0.0
        w, z = SPRING_W, SPRING_Z
        for _ in range(steps if dt > 0 else 0):
            for k in BASE:
                goal = float(target.get(k, 0))
                acc = w * w * (goal - st["x"][k]) - 2 * z * w * st["v"][k]
                st["v"][k] += acc * dt
                st["x"][k] += st["v"][k] * dt
        st["t"] = t
        snap = dict(st["x"])
        st["seen"][key] = snap
        if len(st["seen"]) > 64:                                          # помним последние кадры — для следа движения
            for old in sorted(st["seen"])[:-48]:
                del st["seen"][old]
        out = dict(target)
        out.update(snap)
        return out

    def _pen(self, c):
        return Sketch(c, COLORS[self.look["ink"]]) if self.look.get("draw") else c

    def _actor(self, c, aid, t, ink, measure=False):
        """Герой в момент t: фигура, предмет, значок, удар, пыль. measure — только посчитать точки, не рисовать."""
        w = self.w
        a = self.actors[aid]
        pose, emo, prop, effect, talk = self.state(aid, t)
        x, facing = self.where(aid, t)
        front = self._front
        size = self.fig * a["scale"]
        hang = self.carried(aid, t)
        tr = self.trashed.get(aid) if hasattr(self, "trashed") else None
        if tr and tr[0] <= t < tr[0] + TRASH_IN:                          # проваливается в корзину: сжимается в неё
            k = (t - tr[0]) / TRASH_IN
            r_ = self.icons.trash_rect(t)
            bx, by = r_[0] + r_[2] / 2, r_[1] + r_[3] * 0.35
            sz = size * (1 - 0.85 * ease(k))
            pose = pose_of("surprised")
            pts, r = skeleton(pose, bx, by + sz * 0.9 * ease(k), sz, facing, True)
            if measure:
                return pts["hand1"], pts, r
            draw_figure(c, pts, r, a["color"], self.look, "surprised", 0.0, 0, sz)
            return pts["hand1"], pts, r
        if tr and tr[1] is not None and tr[1] <= t < tr[1] + TRASH_OUT:   # выпрыгивает: дугой из корзины
            k = (t - tr[1]) / TRASH_OUT
            r_ = self.icons.trash_rect(t)
            pose = dict(pose_of("cheer"), dy=(self.ground - r_[1]) / size * 0.6 * (1 - k) + 0.3 * math.sin(math.pi * k))
            emo = "happy"
        if hang:
            m = size * 0.35                                               # не за краем кадра: герой всегда виден
            hang = dict(hang, head=(max(m, min(self.w - m, hang["head"][0])), hang["head"][1]),
                        grip=(max(m, min(self.w - m, hang.get("grip", hang["head"])[0])), hang.get("grip", hang["head"])[1]))
        if hang:                                                         # висит на курсоре или падает — болтает руками-ногами
            g = math.sin(t * 13)
            pose = dict(BASE, sh1=150 + 20 * g, el1=30, sh2=-150 + 20 * g, el2=-30, hip1=12 + 18 * g, kn1=-25, hip2=-12 - 18 * g,
                        kn2=-35, head=-10) if not hang["falling"] else dict(pose_of("surprised"), hip1=30 * g, kn1=-50, hip2=-30 * g, kn2=-40)
            emo, front = ("surprised" if hang["falling"] else "angry"), True
            pose = self._smooth(aid, t, pose)
            pts, r = skeleton(pose, hang["head"][0], self.ground, size, facing, True)
            if hang.get("by") == "foot":                                   # за ногу: чем выше поднял, тем больше вниз головой
                anchor, (hx, hy) = pts["foot1"], hang["grip"]
                lifted = max(0.0, min(1.0, (self.ground - hy) / (size * 0.95)))
                ang = math.radians(180 * ease(lifted) + hang["swing"] * lifted)
            elif hang.get("flip"):                                         # брошен вниз головой — переворачивается в полёте
                anchor, (hx, hy) = pts["hip"], (hang["head"][0], hang["head"][1] + size * 0.4)
                ang = math.radians(hang["flip"])
            else:
                anchor, (hx, hy) = pts["head"], hang["head"]
                ang = math.radians(hang["swing"])
            dx, dy = hx - anchor[0], hy - anchor[1]
            pts = {k: (hx + (px + dx - hx) * math.cos(ang) - (py + dy - hy) * math.sin(ang),
                       hy + (px + dx - hx) * math.sin(ang) + (py + dy - hy) * math.cos(ang)) for k, (px, py) in pts.items()}
        else:
            kn = self.knocked(aid, t)
            if kn:                                                         # получил удар: вздрогнул или отлетел
                phase, k, info = kn
                if phase == "block":                                        # удар в блок: качнулся назад, руки держит
                    jolt = math.sin(math.pi * min(1.0, k))
                    pose = dict(pose, torso=pose["torso"] - 10 * jolt, head=pose["head"] - 6 * jolt)
                elif phase == "flinch":
                    jolt = math.sin(math.pi * min(1.0, k))
                    pose = dict(pose, torso=pose["torso"] - 22 * jolt, head=pose["head"] - 18 * jolt, sh1=pose["sh1"] + 25 * jolt,
                                sh2=pose["sh2"] + 25 * jolt)
                    emo = "surprised"
                elif phase == "fly":                                       # дугой назад, кувыркаясь
                    pose = dict(mix(pose_of("surprised"), pose_of("lie"), ease(k)), rot=100 * ease(k),
                                dy=0.28 * math.sin(math.pi * k) * (1.3 if info["dist"] > 0.21 else 1.0) - 0.48 * ease(k) ** 3,
                                hip1=40 * math.sin(math.pi * k), kn1=-70 * math.sin(math.pi * k))
                    emo = "surprised"
                elif phase == "slide":                                     # юзом по полу
                    pose = dict(pose_of("lie"), rot=90, sh1=170 - 25 * k, sh2=160 - 20 * k)
                    emo = "sad"
                elif phase == "rise":                                      # встаёт: лёжа → на корточках → стоя
                    lie = pose_of("lie")
                    pose = mix(lie, pose_of("crouch"), ease(min(1.0, k / 0.5))) if k < 0.5 else \
                        mix(pose_of("crouch"), pose, ease((k - 0.5) / 0.5))
                    emo = "angry"
                front = False
            land = self.landed(aid, t)
            if land is not None and land < 0.35:                          # приземлился: присел, пружинит, встаёт
                pose = mix(pose, pose_of("crouch"), 0.85 * math.sin(math.pi * min(1.0, land / 0.35)) ** 0.7)
            if kn and kn[0] == "rise_rag":                                  # встаёт: присел — выпрямился
                pose = mix(pose_of("crouch"), pose, ease(kn[1]))
            pose = self._smooth(aid, t, pose)
            pts, r = skeleton(pose, x * w, self.ground, size, facing, front)
            if kn and kn[0] in ("ragdoll", "rise_rag"):                    # тело — из расчёта физики
                from . import ragdoll as RG

                sim = self._rag[kn[2]["rag"]]
                if kn[0] == "ragdoll":
                    pts = dict(RG.sample(sim, kn[1]))
                else:
                    lay = RG.sample(sim, sim["rest"])
                    q = ease(min(1.0, kn[1] * 1.4))
                    pts = {k_: (lay[k_][0] + (pts[k_][0] - lay[k_][0]) * q, lay[k_][1] + (pts[k_][1] - lay[k_][1]) * q)
                           for k_ in pts}
                emo = "surprised" if kn[0] == "ragdoll" else "angry"
                front = False
            low = max(py for k_, (px, py) in pts.items() if k_ != "head")
            low = max(low, pts["head"][1] + r)
            if low > self.ground + size * 0.01:                            # сальто и падения: никто не уходит под пол
                pts = {k_: (px, py - (low - self.ground)) for k_, (px, py) in pts.items()}
            elif 0 < self.ground - low < size * 0.1 and self._live_move(aid, t):   # живая запись почти касается пола —
                pts = {k_: (px, py + (self.ground - low)) for k_, (px, py) in pts.items()}   # прижать (у нас другие пропорции)
            if land is not None and land < 0.25 and not measure:
                draw_dust(c, pts, self.ground, size, land * 2)
            if kn and kn[0] == "block" and kn[1] < 0.35 and not measure and not getattr(self, "_ghost", False):
                draw_impact(c, pts["hand1"], size * 0.8, t)                 # искры от удара в блок
            if kn and kn[0] in ("slide",) and not measure and not getattr(self, "_ghost", False):
                draw_dust(c, {"foot1": pts["head"], "foot2": pts["hip"]}, self.ground, size, t)
        xs = [px for px, _py in pts.values()]                                # вся фигура — в кадре (и голова, и ноги)
        edge = size * 0.12 + r
        shift = (edge - min(xs)) if min(xs) < edge else ((self.w - edge) - max(xs)) if max(xs) > self.w - edge else 0.0
        if shift:
            pts = {k: (px + shift, py) for k, (px, py) in pts.items()}
        if measure:
            return pts["hand1"], pts, r
        if self.look.get("trails") and not getattr(self, "_ghost", False):
            fast = hang is not None or pose.get("_hit", 0) > 0.25 or \
                abs(x - self.where(aid, max(0.0, t - 0.05))[0]) * w / 0.05 > size * 1.5
            if fast:                                                     # след быстрого движения: две бледные копии позади
                self._ghost = True
                try:
                    for back, alpha in ((0.08, 0.14), (0.04, 0.28)):
                        c.push_group()
                        self._actor(c, aid, max(0.0, t - back), ink)
                        c.pop_group_to_source()
                        c.paint_with_alpha(alpha)
                finally:
                    self._ghost = False
        speed = abs(x - self.where(aid, max(0.0, t - 0.06))[0]) * w / 0.06
        if speed > size * 1.2:                                           # бежит быстро — линии скорости позади
            draw_speed_lines(c, pts, size, -1 if x > self.where(aid, max(0.0, t - 0.06))[0] else 1, a["color"])
        if self.look.get("smear") and not getattr(self, "_ghost", False):  # растяжки на быстрых кистях и стопах
            prev = self.__dict__.setdefault("_prev", {}).get(aid)
            if prev and 0 < t - prev[0] < 0.1:
                for key in ("hand1", "hand2", "foot1", "foot2"):
                    a_, b_ = prev[1][key], pts[key]
                    if math.dist(a_, b_) > size * 0.12:
                        draw_smear(c, a_, b_, size * 0.07, a["color"])
            self._prev[aid] = (t, dict(pts))
        draw_figure(c, pts, r, a["color"], self.look, emo if emo in EMOTIONS else "neutral", talk, 0 if front else facing, size)
        if prop:
            draw_hand_prop(self._pen(c), prop, pts["hand1"], facing, size, a["color"])
        if effect:
            draw_effect(c, effect, pts["head"], r, t, ink)
        if pose.get("_hit", 0) > 0.72:
            draw_impact(c, pts[pose.get("_hand", "hand1")], size, t)
        if pose.get("_land"):
            draw_dust(c, pts, self.ground, size, t)
        return pts["hand1"], pts, r


def _accent_of(rgb):
    """Цвет → акцент белой доски (красный, оранжевый, синий) или None — тогда это линия маркера."""
    import colorsys

    hh, ss, vv = colorsys.rgb_to_hsv(*rgb)
    if ss < 0.45 or vv < 0.7:
        return None
    if hh < 0.04 or hh > 0.93:
        return COLORS["red"]
    if hh < 0.17:
        return COLORS["orange"]
    if 0.5 <= hh <= 0.72:
        return COLORS["blue"]
    return None


class Sketch:
    """Рисование «маркером»: заливки становятся контуром графитом, яркие цвета — тремя акцентами доски.
    Обёртка над контекстом cairo — те же функции рисования предметов работают и для белой доски."""

    def __init__(self, c, ink):
        self._c, self._ink, self._accent = c, ink, None

    def __getattr__(self, name):
        return getattr(self._c, name)

    def set_source_rgb(self, r, g, b):
        self._accent = _accent_of((r, g, b))
        self._c.set_source_rgb(*(self._accent or self._ink))

    def fill(self):
        self._c.fill() if self._accent else self._c.stroke()

    def fill_preserve(self):
        self._c.fill_preserve() if self._accent else self._c.stroke_preserve()


def _circle(center, r, n=24):
    """Окружность ломаной — по ней маркер обводит голову."""
    a0 = -math.pi * 0.6
    return [(center[0] + r * math.cos(a0 + 2 * math.pi * i / n), center[1] + r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n + 1)]


def _cut(paths, k):
    """Пройденная маркером часть путей (доля k общей длины) и где сейчас кончик."""
    lens = [[math.dist(a, b) for a, b in zip(p, p[1:])] for p in paths]
    total = sum(sum(x) for x in lens) or 1.0
    left = total * max(0.0, min(1.0, k))
    out, tip = [], paths[0][0] if paths and paths[0] else (0, 0)
    for p, ls in zip(paths, lens):
        if left <= 0:
            break
        done = [p[0]]
        for (a, b), ln in zip(zip(p, p[1:]), ls):
            if left >= ln:
                done.append(b)
                left -= ln
            else:
                q = left / ln if ln else 1
                done.append((a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q))
                left = 0
                break
        out.append(done)
        tip = done[-1]
    return out, tip


def reveal(c, cairo, draw, k, strokes, fig):
    """Маркер проявляет нарисованное: draw(cc) рисует часть целиком (во временный слой), видна только полоса,
    по которой прошёл маркер. strokes — свои линии части (кости героя, земля): маркер идёт по ним, как рука;
    без них — змейкой рядами по рамке рисунка (как «сетка» в srt-whiteboard-animation). Возвращает кончик маркера на экране."""
    m = c.get_matrix()
    rec = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    rc = cairo.Context(rec)
    rc.set_matrix(m)
    draw(rc)
    x, y, bw, bh = rec.ink_extents()
    if bw <= 0 or bh <= 0:
        return None
    if strokes:
        paths = [[m.transform_point(*pt) for pt in p] for p in strokes if len(p) > 1]
        width = max(6.0, fig * m.xx * 0.05)
        rest = max(0.0, (k - 0.88) / 0.12)                              # напоследок проявляются лицо и мелочи
        k = min(1.0, k / 0.88)
    else:
        rest = 0.0
        rows = max(3, int(bh / max(8.0, fig * 0.08)))
        step = bh / rows
        paths, cur = [], []
        for i in range(rows):
            yy = y + step * (i + 0.5)
            row = [(x, yy), (x + bw, yy)] if i % 2 == 0 else [(x + bw, yy), (x, yy)]
            cur += row
        paths = [cur]
        width = step * 1.45
    done, tip = _cut(paths, k)
    c.save()
    c.identity_matrix()
    c.push_group_with_content(cairo.CONTENT_ALPHA)
    c.set_line_width(width)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_join(cairo.LINE_JOIN_ROUND)
    c.set_source_rgba(0, 0, 0, 1)
    for p in done:
        if len(p) > 1:
            c.move_to(*p[0])
            for pt in p[1:]:
                c.line_to(*pt)
            c.stroke()
    if rest:
        c.set_source_rgba(0, 0, 0, rest)
        c.rectangle(x, y, bw, bh)
        c.fill()
    mask = c.pop_group()
    c.set_source_surface(rec, 0, 0)
    c.mask(mask)
    c.restore()
    return tip


def draw_marker(c, tip, h, t):
    """Маркер в руке: кончик на линии, корпус уходит вправо-вниз, колпачок красный; чуть дрожит, как в руке."""
    c.save()
    c.identity_matrix()
    x, y = tip[0] + math.sin(t * 23) * 0.6, tip[1] + math.cos(t * 19) * 0.6
    c.translate(x, y)
    c.rotate(math.radians(-38))
    L, W = h * 0.2, h * 0.034
    c.set_source_rgba(0, 0, 0, 0.12)                                   # тень
    c.rectangle(W * 0.6, -W / 2 + W * 0.5, L, W)
    c.fill()
    c.set_source_rgb(0.18, 0.18, 0.2)                                  # кончик
    c.move_to(0, 0)
    c.line_to(W * 0.75, -W * 0.32)
    c.line_to(W * 0.75, W * 0.32)
    c.close_path()
    c.fill()
    c.set_source_rgb(0.93, 0.93, 0.91)                                 # корпус
    _round_rect(c, W * 0.7, -W / 2, L * 0.72, W, W * 0.2)
    c.fill_preserve()
    c.set_source_rgb(0.55, 0.55, 0.55)
    c.set_line_width(max(1.0, h * 0.0015))
    c.stroke()
    c.set_source_rgb(0.85, 0.22, 0.2)                                  # колпачок
    _round_rect(c, W * 0.7 + L * 0.72, -W * 0.55, L * 0.3, W * 1.1, W * 0.3)
    c.fill()
    c.restore()


def load_background(path, size):
    """Картинка фона (смешанный режим) → поверхность cairo, обрезанная под кадр."""
    import cairo
    from PIL import Image

    w, h = size
    im = Image.open(path).convert("RGB")
    k = max(w / im.width, h / im.height)
    im = im.resize((max(w, int(im.width * k)), max(h, int(im.height * k))))
    left, top = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((left, top, left + w, top + h))
    data = bytearray(im.convert("RGBA").tobytes("raw", "BGRA"))
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, w, h, w * 4)


def render_frames(spec, style, size, secs, background=None, words=None):
    """Генератор кадров (BGRA-байты) сцены."""
    import cairo

    w, h = size
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    c = cairo.Context(surface)
    bg = load_background(background, size) if background else None
    scene = Scene(spec, style, size, secs, bg, words)
    for i in range(int(round(secs * FPS))):
        scene.render(c, scene.scene_time(i / FPS), cairo)
        surface.flush()
        yield bytes(surface.get_data())


def available():
    try:
        import cairo  # noqa: F401

        return True
    except ImportError:
        return False


def scene_sounds(spec, style, size, secs, out, transition=False):
    """Дорожка звуков сцены (wav рядом с клипом) и проверка, что каждый удар слышен на своём кадре.
    spec["sounds"] == False — сцена без звуков. Возвращает путь к wav или None."""
    if (spec or {}).get("sounds") is False:
        return None
    from . import sfx as S

    scene = Scene(spec, style, size, secs)
    events = scene.sound_events()
    if scene.stops():                          # пауза на ударе: звуки после неё — позже, вместе с картинкой
        events = [dict(e, t=scene.video_time(e["t"])) for e in events]
    stop = None
    if scene.beat == "turn":                   # поворот: тишина перед самым сильным ударом, удар — громче всех
        big = [e for e in events if e["kind"] in ("punch", "thud", "stinger")]
        if big:
            hit = max(big, key=lambda e: S.LEVEL_DB[e["kind"]] + e.get("gain_db", 0))
            hit["gain_db"] = hit.get("gain_db", 0) + 3
            stop = (max(0.0, hit["t"] - 0.7), hit["t"] - 0.03)
            events = [e for e in events if e is hit or not (stop[0] <= e["t"] < stop[1])]
    elif scene.beat in ("quiet", "ending"):
        for e in events:
            e["gain_db"] = e.get("gain_db", 0) - 4
    if transition:
        events.append({"t": 0.33, "kind": "whoosh", "pan": 0.0, "gain_db": 7, "args": {"dur": 0.55}})
    track, placed = S.render(events, secs, stop=stop)
    path = pathlib.Path(str(out)).with_suffix("").with_suffix(".sfx.wav")
    S.save_wav(path, track)
    report = S.sync_report(track, placed)
    if report["off"]:
        log.info("звуки сцены не на месте: %s", report["off"][:5])
    return str(path)


def anim_clip(spec, style, voice_file, secs, size, out, ass=None, sfx=None, lead=0.0, background=None, words=None):
    """Сцена мультфильма → клип со звуком (голос, звук перехода) и субтитрами — тем же путём, что слайды студии."""
    from . import studio

    w, h = size
    sfx = scene_sounds(spec, style, size, secs, out, transition=bool(sfx)) or sfx
    a_in, a_filter = studio._audio_in(voice_file, secs, sfx, lead)
    shifted = [(a + lead, b + lead, x) for a, b, x in (words or [])]
    video = "[0:v]format=yuv420p{cap},fade=t=in:st=0:d=0.3,fade=t=out:st={fo:.2f}:d=0.3[v]".format(
        cap=studio._caption_filter(ass), fo=max(0, secs - 0.3))
    cmd = [studio.ffmpeg(), "-hide_banner", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", "{}x{}".format(w, h),
           "-r", str(FPS), "-i", "-"] + [str(x) for x in a_in] + ["-filter_complex", video + ";" + a_filter, "-map", "[v]", "-map", "[a]",
                                                                "-t", "{:.2f}".format(secs)] + studio.VIDEO_OUT[:-2] + ["-r", str(FPS)] + \
        studio.AUDIO_OUT + [str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for frame in render_frames(spec, style, size, secs, background, shifted):
            proc.stdin.write(frame)
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait(timeout=300) != 0:
            raise studio.StudioError("ffmpeg: " + (err.strip().splitlines() or ["ошибка"])[-1][:200])
    except BrokenPipeError:
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait()
        raise studio.StudioError("ffmpeg: " + (err.strip().splitlines() or ["ошибка"])[-1][:200]) from None
    return out


VOCAB = ("Движения (do) — ТОЛЬКО эти слова: {} — позы держатся; walk/run/sneak/crawl/fly/jump двигают героя к x (0 — левый край, "
         "1 — правый), у других x — рывок на месте. Предмет: \"prop\" — взял и держит, пока не \"drop\": true; "
         "give — передать предмет другому (\"target\": id), throw — бросить (\"target\": id — поймает, или \"at\": x — упадёт там). "
         "\"view\": \"front\" — лицом к зрителю (cheer, wave, shrug, dance, bow — и так лицом). "
         "Эмоции (emotion): {}. Предмет в руке (prop): {}. Значок над головой (effect): {}. Предметы сцены (props.kind): {}. "
         "Камера: [{{\"from\", \"to\", \"zoom\": 1.1–1.8, \"on\": id героя}}]. Стиль whiteboard (белая доска): картинка рисуется маркером "
         "по ходу рассказа — \"draw\": [{{\"what\": id героя или kind предмета, \"word\": слово из текста, на котором рисовать}}] "
         "(сначала место, потом герои; действия — после того, как всё нарисовано, примерно с 0.6 сцены). "
         "Стиль neon_desktop (рабочий стол): \"windows\": [{{\"id\": \"w1\", \"x\", \"y\", \"w\", \"h\" (доли кадра), \"color\"}}]; "
         "курсор — персонаж: \"cursor\": [{{\"t\": доля сцены, \"x\", \"y\", \"grab\": id окна или героя | \"release\": true | \"click\": true}}] — "
         "тащит окна, хватает героя (\"by\": \"foot\" — за ногу, вниз головой; x, y можно не писать — сам найдёт героя) и роняет; "
         "\"mood\": \"angry\" (краснеет, дрожит) | \"happy\" | \"calm\"; \"click\": \"start\" — открыть меню «Пуск»; "
         "\"into\": \"trash\" — курсор ныряет в корзину и исчезает до конца сцены; "
         "иконки (по умолчанию folder, file, music и корзина trash; свои — \"icons\": [{{\"id\", \"kind\": folder|file|music|game|trash, \"x\", \"y\"}}]): "
         "курсор берёт иконку (\"grab\": id) и, отпустив на быстром движении, швыряет — она летит, отскакивает и сбивает героя; "
         "пинок с \"target\": id иконки отправляет её в полёт; отпустить героя над корзиной — провалится и выпрыгнет к своему следующему движению; \"hit\": id героя — курсор с замахом врезается в героя, тот отлетает; удар (punch/kick/fight) с \"target\": id окна разбивает окно. "
         "Живые движения из записей людей: jumpkick (пинок в прыжке), spinkick (с разворота), backflip (сальто назад), "
         "sideflip, cartwheel (колесо), faceplant (падение лицом), slip (поскользнулся), rugpull (выдернули ковёр), "
         "duck (уклон — пригнулся), slide (подкат), roll (кувырок), crawl, climb (по лестнице), танцы breakdance, kazachok, "
         "moonwalk, ballet, guard (стойка защиты — блок: удар спереди не отбрасывает), diveroll (нырок с кувырком на бегу); "
         "уклон, подкат, кувырок, сальто и прыжок в момент удара — удар мимо, летящая иконка пролетает над пригнувшимся; "
         "walk, run, jump, punch, kick — тоже живые. В стиле action сильный удар роняет героя по физике (отлетает, бьётся о пол, "
         "окна и края экрана, встаёт); в других стилях так же с \"physics\": true. Удар по герою: \"target\": id героя — нападающий сам подшагнёт, от каждого удара цель вздрагивает, от последнего "
         "в серии — отлетает дугой, едет по полу и встаёт (~1,5 с, не ставь цели движений на это время).").format(
    ", ".join(ACTIONS), ", ".join(EMOTIONS), ", ".join(HAND_PROPS), ", ".join(EFFECTS), ", ".join(SCENE_PROPS))
