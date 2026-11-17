"""Blender: 3D-героиня Мия (assets/heroine/heroine.glb, сделана TRELLIS из рисунка-образца) со скелетом и движениями.

Просто управлять:
    hero = load(location, height, yaw)          # из готового assets/heroine/heroine.blend (скелет + движения)
    total = play(hero, ["wave", "jump"], start=1)   # движения встают в ряд на шкале времени, с плавными переходами
Движения — обычные Action в Blender (Hero_idle, Hero_wave, …): их можно открыть, поправить руками и сохранить.
Файл героя собирает make_blend() (blender -b -P hero3d.py -- make). Модель: рост 1, лицом к −Y, ноги внизу."""
import math
import os
import sys

import bpy
from mathutils import Euler, Vector

MODEL = os.environ.get("HERO_MODEL", "voxel")                          # voxel — код, trellis — модель нейросети
GLB = os.path.join(os.path.dirname(__file__), "..", "assets", "heroine", "heroine.glb")
# кости: голова, хвост, родитель (координаты модели; сторона персонажа: левая = +X)
BONES = {
    "hips": ((0, 0, -0.21), (0, 0, -0.08), None),
    "spine": ((0, 0, -0.08), (0, 0, 0.13), "hips"),
    "head": ((0, 0, 0.13), (0, 0, 0.48), "spine"),
    "hair": ((0, 0.1, 0.16), (0, 0.16, -0.16), "head"),
    "upper_arm.L": ((0.12, 0, 0.085), (0.215, 0, 0.02), "spine"),
    "fore_arm.L": ((0.215, 0, 0.02), (0.315, 0, -0.05), "upper_arm.L"),
    "upper_arm.R": ((-0.12, 0, 0.085), (-0.215, 0, 0.02), "spine"),
    "fore_arm.R": ((-0.215, 0, 0.02), (-0.315, 0, -0.05), "upper_arm.R"),
    "thigh.L": ((0.062, 0, -0.21), (0.062, 0, -0.35), "hips"),
    "shin.L": ((0.062, 0, -0.35), (0.062, 0, -0.49), "thigh.L"),
    "thigh.R": ((-0.062, 0, -0.21), (-0.062, 0, -0.35), "hips"),
    "shin.R": ((-0.062, 0, -0.35), (-0.062, 0, -0.49), "thigh.R"),
}
MOVES = ("idle", "wave", "jump", "walk", "dance", "turn")
SECONDS = {"idle": 1.5, "wave": 2.0, "jump": 1.6, "walk": 2.0, "dance": 2.4, "turn": 2.0}


def _in_arm(p):
    """Рукав по замеру сетки 17.11.2026: верх от (0.14, 0.13) к (0.34, 0), низ от (0.16, −0.01) вниз до −0.095;
    ниже — висящие пряди, их к руке не привязываем."""
    ax = abs(p.x)
    top = 0.13 - 0.675 * (ax - 0.14) + 0.015
    bottom = max(-0.095, -0.01 - 0.85 * (ax - 0.16))
    return bottom <= p.z <= top


def _bone_of(p):
    """Кость для точки сетки — одна, без смешивания: блочный персонаж двигается жёсткими частями, как кукла из
    кубиков; смешанные веса давали «осколки» на рукавах (17.11.2026)."""
    ax = abs(p.x)
    side = ".L" if p.x > 0 else ".R"
    if p.y > 0.06 and -0.19 < p.z < 0.15 and ax < 0.24:                 # длинные волосы за спиной
        return "hair"
    if p.z > 0.15:
        return "head"
    if 0.11 < ax < 0.245 and -0.17 < p.z < 0.13 and p.y >= 0.045:        # пряди сбоку за руками
        return "hair"
    if ax >= 0.125 and -0.135 < p.y < 0.045 and _in_arm(p):              # рукав: плечо → локоть → кисть
        return ("upper_arm" if ax < 0.215 else "fore_arm") + side
    if p.z < -0.21:                                                      # ноги: бедро и голень своей стороны
        return ("thigh" if p.z > -0.35 else "shin") + side
    if p.z < -0.08:
        return "hips"
    return "spine"


def _weights(mesh):
    groups = {n: mesh.vertex_groups.new(name=n) for n in BONES}
    for v in mesh.data.vertices:
        groups[_bone_of(v.co)].add([v.index], 1.0, "REPLACE")


def build(parent=None, location=(0, 0, 0), height=1.0, yaw=0.0):
    """Загрузить героиню, поставить скелет и веса. Возвращает (armature, mesh). Ноги — в точке location."""
    if MODEL == "voxel":                                               # модель строит код (hero_voxel.py)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hero_voxel

        mesh = hero_voxel.make_mesh(list(BONES))
    else:                                                              # запасной вариант: модель TRELLIS
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(GLB))
        new = [o for o in bpy.data.objects if o not in before]
        mesh = [o for o in new if o.type == "MESH"][0]
        mw = mesh.matrix_world.copy()
        mesh.parent = None
        mesh.matrix_world = mw
        bpy.context.view_layer.objects.active = mesh
        for o in new:
            if o is not mesh:
                bpy.data.objects.remove(o, do_unlink=True)
        mesh.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    arm_data = bpy.data.armatures.new("hero_rig")
    arm = bpy.data.objects.new("hero_rig", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, (h, t, par) in BONES.items():
        b = arm_data.edit_bones.new(name)
        b.head, b.tail = Vector(h), Vector(t)
        b.align_roll(Vector((0, -1, 0)))                               # ось Z каждой кости — вперёд: сгибы предсказуемы
        if par:
            b.parent = arm_data.edit_bones[par]
            b.use_connect = Vector(h) == Vector(BONES[par][1])
    bpy.ops.object.mode_set(mode="OBJECT")
    if MODEL != "voxel":
        _weights(mesh)
    mesh.parent = arm
    mod = mesh.modifiers.new("rig", "ARMATURE")
    mod.object = arm
    arm.scale = (height, height, height)
    arm.location = Vector(location) + Vector((0, 0, 0.5 * height))
    arm.rotation_euler = (0, 0, yaw)
    if parent:
        arm.parent = parent
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
    return arm, mesh


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def plan(moves):
    out, t = [], 0.0
    for m in [m for m in (moves or []) if m in SECONDS] or ["idle", "wave", "jump"]:
        out.append((m, t, t + SECONDS[m]))
        t += SECONDS[m]
    return out, t


def pose_at(arm, t, steps, base_loc=None, base_yaw=0.0):
    """Поза в момент t. Оси костей (Z каждой смотрит вперёд), проверено рендером 17.11.2026:
    рука .L поднимается при +Z, .R — при −Z; предплечье сгибается так же; бедро и корпус при +X — назад
    (вперёд — минус); голень сгибается при +X; голова набок — Z, поворот — Y."""
    R = {n: [0.0, 0.0, 0.0] for n in BONES}
    lift, yaw = 0.0, 0.0
    breath = math.sin(2 * math.pi * t / 2.6)
    R["spine"][0] = -1.5 * breath
    R["head"][2] = 3 * math.sin(2 * math.pi * t / 3.2)
    R["hair"][0] = 3 * math.sin(2 * math.pi * t / 3.2 - 0.8)

    def raise_arm(side, deg):                                          # плюс — вверх, для обеих сторон
        R["upper_arm" + side][2] += deg if side == ".L" else -deg

    def bend_elbow(side, deg):
        R["fore_arm" + side][2] += deg if side == ".L" else -deg
    for s_ in (".L", ".R"):                                            # руки из А-позы вдоль тела, локти чуть согнуты
        raise_arm(s_, -38 + 2 * breath)
        bend_elbow(s_, 8)
    for m, a, b in steps:
        if not a <= t < b:
            continue
        d, u = t - a, (t - a) / (b - a)
        env = ease(u / 0.18) * ease((1 - u) / 0.18)
        if m == "wave":                                                # правая рука вверх, ладонь машет, голова набок
            raise_arm(".R", 112 * env)                                 # рука вверх-наружу, лицо открыто
            R["upper_arm.R"][0] += -20 * env                           # чуть вперёд, к зрителю
            bend_elbow(".R", (35 + 30 * math.sin(2 * math.pi * d * 2.3)) * env)
            R["head"][2] += -8 * env
            R["spine"][2] += -3 * env
        elif m == "jump":
            if d < 0.38:                                               # подготовка: присела, руки назад, корпус вперёд
                k = ease(d / 0.38)
                for s_ in (".L", ".R"):
                    R["thigh" + s_][0] += -50 * k
                    R["shin" + s_][0] += 85 * k
                    R["upper_arm" + s_][0] += 30 * k
                R["spine"][0] += -18 * k
                lift = -0.075 * k
            elif d < 1.08:                                             # прыжок: руки вверх, волосы взлетают позже
                k = (d - 0.38) / 0.7
                lift = 0.3 * 4 * k * (1 - k)
                up = ease(min(1, k * 3)) * (1 - ease((k - 0.75) / 0.25))
                for s_ in (".L", ".R"):
                    raise_arm(s_, 135 * up)
                    R["shin" + s_][0] += 30 * math.sin(math.pi * k)
                R["spine"][0] += 6 * math.sin(math.pi * k)
                R["hair"][0] += -30 * math.sin(math.pi * k)
            else:                                                      # приземление: присела, выпрямилась
                k = (d - 1.08) / 0.52
                bend = max(0.0, math.exp(-k * 4) * math.cos(k * 7))
                for s_ in (".L", ".R"):
                    R["thigh" + s_][0] += -40 * bend
                    R["shin" + s_][0] += 70 * bend
                R["spine"][0] += -10 * bend
                R["hair"][0] += 18 * bend
                lift = -0.06 * bend
        elif m == "walk":                                              # шаги на месте: колено вперёд-вверх, руки в противоход
            ph = math.sin(2 * math.pi * d / 0.7)
            for s_, sg in ((".L", 1), (".R", -1)):
                up = max(0.0, ph * sg)
                R["thigh" + s_][0] += -55 * up * env
                R["shin" + s_][0] += 75 * up * env
                R["upper_arm" + s_][0] += 28 * ph * sg * env
            R["spine"][1] += 6 * ph * env
            R["head"][1] += -4 * ph * env
            lift = 0.012 * abs(ph) * env
        elif m == "dance":                                             # бёдра качаются, руки по очереди вверх
            ph = math.sin(2 * math.pi * d / 0.8)
            R["hips"][2] += 8 * ph * env
            R["spine"][2] += -10 * ph * env
            R["head"][2] += 10 * ph * env
            raise_arm(".L", (120 if ph > 0 else 20) * env)
            raise_arm(".R", (20 if ph > 0 else 120) * env)
            bend_elbow(".L", 35 * env)
            bend_elbow(".R", 35 * env)
            R["hair"][2] += -10 * ph * env
            for s_, sg in ((".L", 1), (".R", -1)):
                R["thigh" + s_][0] += -15 * max(0.0, ph * sg) * env
                R["shin" + s_][0] += 25 * max(0.0, ph * sg) * env
            lift = 0.025 * abs(math.sin(2 * math.pi * d / 0.4)) * env
        elif m == "turn":                                              # оборачивается вокруг себя, волосы отстают
            yaw = 2 * math.pi * ease(u)
            R["hair"][1] += -25 * math.sin(math.pi * u)
            lift = 0.02 * math.sin(math.pi * u)
    for n, (x, y, z) in R.items():
        arm.pose.bones[n].rotation_euler = Euler((math.radians(x), math.radians(y), math.radians(z)), "XYZ")
    if base_loc is not None:
        arm.location = Vector(base_loc) + Vector((0, 0, lift * arm.scale.z))
        arm.rotation_euler = (0, 0, base_yaw + yaw)


FPS = 24
BLEND = os.path.join(os.path.dirname(__file__), "..", "assets", "heroine", "heroine.blend")


def make_blend(path=BLEND):
    """Собрать файл героя: сетка, скелет, веса и по одному Action на каждое движение (ключи каждые 2 кадра)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = bpy.data.objects.new("Mia", None)
    bpy.context.scene.collection.objects.link(root)
    arm, mesh = build(parent=root)
    arm.location = (0, 0, 0.5)
    arm.animation_data_create()
    for m in MOVES:
        steps, total = plan([m])
        act = bpy.data.actions.new("Hero_" + m)
        act.use_fake_user = True
        arm.animation_data.action = act
        n = int(round(total * FPS))
        for f in range(0, n + 1, 2):
            pose_at(arm, f / FPS, steps, base_loc=(0, 0, 0.5), base_yaw=0.0)
            for pb in arm.pose.bones:
                pb.keyframe_insert("rotation_euler", frame=f + 1)
            arm.keyframe_insert("location", frame=f + 1)
            arm.keyframe_insert("rotation_euler", frame=f + 1)
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_euler = (0, 0, 0)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(path))


def load(location=(0, 0, 0), height=1.0, yaw=0.0, parent=None, path=BLEND):
    """Добавить героиню из файла героя в текущую сцену. Возвращает её корень (пустышку «Mia»): двигайте его."""
    with bpy.data.libraries.load(os.path.abspath(path)) as (src, dst):
        dst.objects = list(src.objects)
        dst.actions = list(src.actions)
    for o in dst.objects:
        bpy.context.scene.collection.objects.link(o)
    root = [o for o in dst.objects if o.type == "EMPTY" and o.name.startswith("Mia")][0]
    root.location, root.scale, root.rotation_euler = Vector(location), (height,) * 3, (0, 0, yaw)
    if parent:
        root.parent = parent
    return root


def _rig(root):
    return [c for c in root.children if c.type == "ARMATURE"][0]


def play(root, moves, start=1, blend=4):
    """Поставить движения подряд (NLA-дорожка): каждое — Action «Hero_<имя>», переходы по blend кадров.
    Возвращает последний кадр."""
    arm = _rig(root)
    arm.animation_data_create()
    tracks = [arm.animation_data.nla_tracks.new() for _ in range(2)]   # две дорожки по очереди: переходы внахлёст
    for i, t in enumerate(tracks):
        t.name = "moves_%d" % (i + 1)
    f = start
    for i, m in enumerate([m for m in moves if m in SECONDS]):
        strip = tracks[i % 2].strips.new(m, int(f), bpy.data.actions["Hero_" + m])
        strip.blend_in = strip.blend_out = blend
        strip.extrapolation = "NOTHING"
        f = strip.frame_end - blend
    if moves:
        strip.extrapolation = "HOLD_FORWARD"                           # после последнего движения — держит позу
        strip.blend_out = 0
    return int(f + blend)


if __name__ == "__main__" and "make" in sys.argv:
    make_blend()
    print("ГОТОВО", os.path.abspath(BLEND))
