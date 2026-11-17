"""Blender без окна (запускает chloe/live_scene.py): воксельный летающий остров — код строит всё: остров, дерево, пруд,
кубическую героиню. Время года — VOX_SEASON (spring / winter / autumn / night).
Камера облетает остров по кругу (идеальная петля), падают лепестки. Запуск: blender -b -P bl_voxel.py -- OUT_DIR"""
import math
import os
import random
import sys

import bpy
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
FRAMES = int(os.environ.get("VOX_FRAMES", 90))
RW, RH = int(os.environ.get('VOX_W', 540)), int(os.environ.get('VOX_H', 960))
random.seed(4)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def jitter(c, k=0.05):
    d = random.uniform(-k, k)
    return tuple(min(1, max(0, v + d)) for v in c)


FACES = [((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
         ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
         ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]),
         ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
         ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
         ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)])]


def srgb_to_lin(c):
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c)


MAT = None


def material():
    global MAT
    if MAT:
        return MAT
    m = bpy.data.materials.new("vox")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.72
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "col"
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bev = nt.nodes.new("ShaderNodeBevel")                              # скруглённые края кубиков
    bev.inputs["Radius"].default_value = 0.07
    nt.links.new(bev.outputs["Normal"], bsdf.inputs["Normal"])
    MAT = m
    return m


def water_material():
    m = bpy.data.materials.new("water")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.35, 0.75, 0.95, 1)
    b.inputs["Roughness"].default_value = 0.04
    b.inputs["IOR"].default_value = 1.33
    b.inputs["Transmission Weight"].default_value = 0.85
    return m


def voxel_mesh(name, vox, size=1.0, origin=(0, 0, 0), parent=None, mat=None):
    """vox: {(x,y,z): rgb}. Только видимые грани, цвет на грань — как пиксельная текстура."""
    verts, faces, cols = [], [], []
    for (x, y, z), c in vox.items():
        for (nx, ny, nz), quad in FACES:
            if (x + nx, y + ny, z + nz) in vox:
                continue
            i = len(verts)
            for qx, qy, qz in quad:
                verts.append(((x + qx) * size - origin[0], (y + qy) * size - origin[1], (z + qz) * size - origin[2]))
            faces.append((i, i + 1, i + 2, i + 3))
            shade = 1.0                                                     # объём даёт настоящий свет
            cols.append(srgb_to_lin(tuple(v * shade for v in c)))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ca = me.color_attributes.new("col", "FLOAT_COLOR", "CORNER")
    for poly, c in zip(me.polygons, cols):
        for li in poly.loop_indices:
            ca.data[li].color = (*c, 1.0)
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    me.materials.append(mat or material())
    if parent:
        ob.parent = parent
    return ob


root = bpy.data.objects.new("root", None)
scene.collection.objects.link(root)

# --- остров ---
SEASON = os.environ.get("VOX_SEASON", "spring")
GRASS, GRASS2 = hexc("#8fe3c8"), hexc("#74d2b6")
EARTH, STONE, STONE2 = hexc("#f0d2a8"), hexc("#7f7aa3"), hexc("#6a6590")
PINK = [hexc(h) for h in ("#ff8fc4", "#ff6fb0", "#ffb3d6", "#ff9ccb", "#f2559c")]
if SEASON == "winter":                                                 # снег на мху и на кроне
    GRASS, GRASS2 = hexc("#f4f8ff"), hexc("#dfe9fb")
    PINK = [hexc(h) for h in ("#ffffff", "#eef4ff", "#dce8ff", "#f6f0ff", "#cfe0ff")]
elif SEASON == "autumn":
    GRASS, GRASS2 = hexc("#c9c46a"), hexc("#b5a955")
    PINK = [hexc(h) for h in ("#f08a3c", "#e0582f", "#f6b44a", "#d9472b", "#f7c46a")]
WATER, WATER2 = hexc("#62c9f5"), hexc("#8fdcff")
BARK = hexc("#5a2e45")
island = {}
R = 11
tops = {}
for x in range(-R - 1, R + 2):
    for y in range(-R - 1, R + 2):
        d = math.hypot(x, y) + random.uniform(-0.6, 0.6)
        if d > R:
            continue
        h = 6 + (1 if math.sin(x * 0.5) + math.cos(y * 0.45) > 0.9 else 0)
        bottom = int(-(R - d) * 1.1) + 2
        tops[(x, y)] = h
        for z in range(bottom, h + 1):
            if z == h:
                c = jitter(random.choice([GRASS, GRASS, GRASS2]))
                if random.random() < 0.07:
                    c = jitter(random.choice(PINK))                    # опавшие лепестки на траве
            elif z >= h - 2:
                c = jitter(EARTH, 0.04)
            else:
                c = jitter(random.choice([STONE, STONE, STONE2]), 0.04)
            island[(x, y, z)] = c
water = {}
for x in range(4, 9):                                                  # пруд
    for y in range(-8, -3):
        if (x, y) in tops and math.hypot(x - 6.5, y + 5.5) < 2.6:
            h = tops[(x, y)]
            island.pop((x, y, h), None)
            water[(x, y, h - 1)] = jitter(random.choice([WATER, WATER2]), 0.03)
            island[(x, y, h - 2)] = jitter(STONE, 0.03)
            tops[(x, y)] = h - 1
# сакура
tx, ty = -4, 3
th = tops[(tx, ty)]
for z in range(th + 1, th + 8):
    island[(tx, ty, z)] = jitter(BARK, 0.03)
    if z < th + 3:
        island[(tx + 1, ty, z)] = jitter(BARK, 0.03)
for bx, by, bz in ((1, 0, 5), (2, 1, 6), (-1, 1, 6), (-2, -1, 5), (0, -2, 6)):
    island[(tx + bx, ty + by, th + bz)] = jitter(BARK, 0.03)
for x in range(-6, 7):
    for y in range(-6, 7):
        for z in range(-4, 5):
            cx, cy, cz = tx + x, ty + y, th + 10 + z
            d = math.hypot(x / 5.6, y / 5.6, z / 3.8) + random.uniform(-0.12, 0.12)
            if d < 1.0 and (cx, cy, cz) not in island:
                island[(cx, cy, cz)] = jitter(random.choice(PINK), 0.03)
voxel_mesh("island", island, parent=root)
wm = voxel_mesh("water", water, parent=root, mat=water_material())
# травинки и цветочки на мху — мелкие тонкие кубики
tuft = {}
for (x, y), h in tops.items():
    if (x, y, h + 1) in island or (x, y, h) not in island or (x, y, h - 1) in water:
        continue
    for k in range(random.randint(0, 3)):
        gx, gy = x * 5 + random.randint(0, 4), y * 5 + random.randint(0, 4)
        tall = random.randint(1, 3)
        col = jitter(random.choice([GRASS, GRASS2, GRASS2] if SEASON == "winter" else [GRASS2, hexc("#5fbf9e"), hexc("#9ff0d4")]), 0.03)
        if random.random() < 0.08:
            col = random.choice([(1, 1, 1), hexc("#ffd36e"), PINK[2]])
        for z in range(tall):
            tuft[(gx, gy, (h + 1) * 5 + z)] = col
voxel_mesh("tufts", tuft, 0.2, parent=root)
wm.scale = (1, 1, 0.92)

# --- кубическая героиня (мелкие кубики 0.25) ---
S = 0.4
SKIN, HAIR, TIP = hexc("#ffe2d4"), hexc("#eef0f8"), hexc("#7cc6ff")
HOOD, TRIM, SHORT = hexc("#f7f8fc"), hexc("#6fb4f5"), hexc("#25294a")
NAVY, CYAN, EYE, EYE2 = hexc("#24305e"), hexc("#4ee6ff"), hexc("#1f3d9c"), hexc("#5aa8ff")
SHOE, SOLE = hexc("#fbfbfd"), hexc("#3a74e0")
hero = {}


def box(x0, x1, y0, y1, z0, z1, col, d=None):
    d = d if d is not None else hero
    for x in range(x0, x1):
        for y in range(y0, y1):
            for z in range(z0, z1):
                d[(x, y, z)] = jitter(col(x, y, z) if callable(col) else col, 0.02)


box(-3, -1, -1, 2, 0, 1, SOLE)
box(1, 3, -1, 2, 0, 1, SOLE)                                           # подошвы
box(-3, -1, -1, 2, 1, 2, SHOE)
box(1, 3, -1, 2, 1, 2, SHOE)
box(-3, -1, -1, 1, 2, 5, lambda x, y, z: TRIM if z == 4 else SHOE)     # гольфы с полоской
box(1, 3, -1, 1, 2, 5, lambda x, y, z: TRIM if z == 4 else SHOE)
box(-3, -1, -1, 1, 5, 7, SKIN)
box(1, 3, -1, 1, 5, 7, SKIN)
box(-3, 3, -1, 2, 7, 9, lambda x, y, z: TRIM if x in (-3, 2) else SHORT)   # шорты с кантом
box(-4, 4, -2, 2, 9, 15, lambda x, y, z: TRIM if z == 9 else HOOD)      # худи
for x, z in ((-1, 13), (-1, 12), (0, 13), (0, 12)):
    pass
hero[(-1, -3, 13)] = jitter(HOOD)                                      # шнурки
hero[(0, -3, 12)] = jitter(HOOD)
box(-3, 3, -2, 1, 15, 16, SKIN)                                        # шея/воротник
for z in range(16, 24):                                                # голова 8×8×8
    for x in range(-4, 4):
        for y in range(-4, 4):
            front = y == -4
            if front and z <= 21 and -3 <= x <= 2:
                c = SKIN                                               # лицо
                if z in (18, 19) and x in (-3, -2, 1, 2):
                    c = EYE if z == 19 else EYE2
                if z == 19 and x in (-3, 1):
                    c = (1, 1, 1)                                      # блик в глазу
                if z == 17 and x in (-1, 0):
                    c = hexc("#e2787f")                                # ротик
            else:
                c = TIP if z <= 17 and not front else HAIR             # волосы, кончики голубые
            hero[(x, y, z)] = jitter(c, 0.02)
for x in range(-4, 4):                                                 # чёлка
    if x % 3 != 0:
        hero[(x, -5, 21)] = jitter(HAIR, 0.02)
    hero[(x, -5, 22)] = jitter(HAIR, 0.02)
for z in range(10, 16):                                                # длинные волосы сзади
    for x in range(-4, 4):
        hero[(x, 3, z)] = jitter(TIP if z < 13 else HAIR, 0.02)
for x in range(-5, 5):                                                 # наушники: дуга и чашки
    hero[(x, 0, 24)] = jitter(NAVY, 0.02)
for sx, out in ((-5, -6), (4, 5)):                                    # чашки наушников, крупные — их видно
    for y in range(-2, 3):
        for z in range(17, 22):
            hero[(sx, y, z)] = jitter(NAVY, 0.02)
            if abs(y) <= 1 and 18 <= z <= 20:
                hero[(out, y, z)] = jitter(CYAN if (y == 0 or z == 19) else NAVY, 0.02)
    hero[(sx, 0, 21)] = jitter(NAVY)
    hero[(sx, 0, 22)] = jitter(NAVY)
    hero[(sx, 0, 23)] = jitter(NAVY)
sleeve = lambda x, y, z: SKIN if z < 10 else (TRIM if z == 10 else HOOD)
box(-6, -4, -1, 1, 9, 15, sleeve)                                      # левая рука
box(4, 6, -1, 1, 9, 15, sleeve)                                        # правая рука


def part_of(x, y, z):
    """Какой части тела принадлежит кубик: голова (с волосами и наушниками), руки, ноги, туловище."""
    if z >= 16 or (y == 3 and z >= 10):
        return "head"
    if x <= -5 and 9 <= z <= 14:
        return "arm_l"
    if x >= 4 and 9 <= z <= 14:
        return "arm_r"
    if z <= 6:
        return "leg_l" if x < 0 else "leg_r"
    return "torso"


# суставы в координатах героини (единицы S) и родитель
JOINTS = {"torso": ((0, 0, 7), None), "head": ((0, 0, 16), "torso"), "arm_l": ((-5, 0, 15), "torso"),
          "arm_r": ((5, 0, 15), "torso"), "leg_l": ((-2, 0, 7), None), "leg_r": ((2, 0, 7), None)}
hx, hy = 3, -3
HX, HY, HZ = hx * 1.0 + 0.5, hy * 1.0 + 0.5, tops[(hx, hy)] + 1
hero_obj = bpy.data.objects.new("hero", None)
scene.collection.objects.link(hero_obj)
hero_obj.parent = root
hero_obj.location = (HX, HY, HZ)
hero_obj.rotation_euler = (0, 0, math.radians(-45))                    # лицом к камере
BODY = {}
for name, ((jx, jy, jz), parent) in JOINTS.items():
    piv = bpy.data.objects.new("j_" + name, None)
    scene.collection.objects.link(piv)
    piv.parent = BODY[parent] if parent else hero_obj
    px, py, pz = JOINTS[parent][0] if parent else (0, 0, 0)
    piv.location = ((jx - px) * S, (jy - py) * S, (jz - pz) * S)
    piv.rotation_mode = "XYZ"
    BODY[name] = piv
for name in JOINTS:
    vox = {k: c for k, c in hero.items() if part_of(*k) == name}
    jx, jy, jz = JOINTS[name][0]
    voxel_mesh("hero_" + name, vox, S, origin=(jx * S, jy * S, jz * S), parent=BODY[name])
pivot = BODY["arm_r"]

# --- лепестки ---
petals = []
pm = {(0, 0, 0): PINK[0]}
for k in range(46):
    p = voxel_mesh("petal%d" % k, {(0, 0, 0): random.choice(PINK)}, 0.3, parent=root)
    p.scale = (1, 1, 0.22)
    petals.append((p, random.uniform(-10, 10), random.uniform(-10, 10), random.random(), random.uniform(0.6, 1.2)))

# --- свет, камера, рендер ---
sky = True
sun = bpy.data.lights.new("sun", "SUN")
sun.energy = 3.2
sun.angle = math.radians(3)
so = bpy.data.objects.new("sun", sun)
scene.collection.objects.link(so)
so.rotation_euler = (math.radians(45), math.radians(10), math.radians(-35))
sun.energy = 1.2 if SEASON == "night" else 4.2
sun.color = (0.62, 0.72, 1.0) if SEASON == "night" else (1.0, 0.82, 0.62)   # луна или тёплое закатное солнце
so.rotation_euler = (math.radians(68), math.radians(0), math.radians(-60))
world = bpy.data.worlds.new("w")
world.use_nodes = True
wn = world.node_tree
st = wn.nodes.new("ShaderNodeTexSky")
st.sky_type = "NISHITA"
st.sun_elevation = math.radians(14)
st.sun_rotation = math.radians(210)
st.sun_disc = False
wn.links.new(st.outputs["Color"], wn.nodes["Background"].inputs["Color"])
wn.nodes["Background"].inputs["Strength"].default_value = 0.12 if SEASON == "night" else 0.55
scene.world = world
cam_data = bpy.data.cameras.new("cam")
cam_data.type = "PERSP"
cam_data.lens = 70
cam_data.dof.use_dof = True
cam_data.dof.aperture_fstop = 1.2
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
target = Vector((0, 0, 6))
cam.location = target + Vector((-58, -58, 40))
cam_data.dof.focus_distance = (cam.location - Vector((3, -3, 10))).length
if os.environ.get("VOX_CLOSE"):                                        # движения: камера ближе к героине, остров снизу
    target = Vector((1.5, -1.5, 9.5))                                  # без пустого неба (17.11.2026: VACE рисовал там озеро)
    cam.location = target + Vector((-30, -30, 17))
    cam_data.dof.focus_distance = (cam.location - Vector((3, -3, 10))).length
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
r = scene.render
r.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = int(os.environ.get("VOX_SAMPLES", 48))
scene.cycles.use_denoising = False
scene.cycles.max_bounces = 4
r.resolution_x, r.resolution_y = RW, RH
r.film_transparent = True
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Punchy"

MOVES = os.environ.get("VOX_MOVES")                                    # «idle,wave,jump,walk,dance» — движения героини
PLAN = []
if MOVES:
    DUR = {"idle": 1.5, "wave": 2.0, "jump": 1.6, "walk": 1.6, "dance": 2.0}
    t0 = 0.0
    for m in [m.strip() for m in MOVES.split(",") if m.strip() in DUR]:
        PLAN.append((m, t0, t0 + DUR[m]))
        t0 += DUR[m]
    FRAMES = int(round(t0 * 15))                                        # 15 рисунков в секунду


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def pose(t):
    """Поза героини в момент t по плану движений. Углы в градусах: руки вниз = 0, рука в сторону вверх — ±150."""
    B = {k: [0.0, 0.0, 0.0] for k in JOINTS}
    lift, squash = 0.0, 1.0
    B["torso"][2] = 0.0
    breath = math.sin(2 * math.pi * t / 2.4)
    B["head"][1] = 3 * math.sin(2 * math.pi * t / 3.0)
    for m, a, b in PLAN:
        if not a <= t < b:
            continue
        u = (t - a) / (b - a)
        env = ease(u / 0.2) * ease((1 - u) / 0.2)                       # плавно вошла и вышла из движения
        if m == "wave":                                                 # машет правой рукой, голова набок
            B["arm_r"][1] = (-150 + 25 * math.sin(2 * math.pi * (t - a) * 2.2)) * env
            B["head"][1] += 8 * env
        elif m == "jump":                                               # присела → прыжок руки вверх → приземление
            d = t - a
            if d < 0.35:
                k = ease(d / 0.35)
                squash, lift = 1 - 0.1 * k, -0.15 * k
                B["arm_l"][0] = B["arm_r"][0] = 35 * k                   # руки назад — замах
            elif d < 1.05:
                k = (d - 0.35) / 0.7
                lift = 1.8 * 4 * k * (1 - k)
                squash = 1.06 if k < 0.5 else 1.0
                B["arm_l"][1], B["arm_r"][1] = 155 * ease(k * 3), -155 * ease(k * 3)
                B["leg_l"][1], B["leg_r"][1] = -8, 8
            else:
                k = (d - 1.05) / 0.55
                squash = 1 - 0.1 * math.exp(-k * 4) * math.cos(k * 9)
                B["arm_l"][1], B["arm_r"][1] = 155 * (1 - ease(k * 1.5)), -155 * (1 - ease(k * 1.5))
        elif m == "walk":                                               # шаги на месте
            ph = math.sin(2 * math.pi * (t - a) / 0.6)
            B["leg_l"][0], B["leg_r"][0] = 32 * ph * env, -32 * ph * env
            B["arm_l"][0], B["arm_r"][0] = -30 * ph * env, 30 * ph * env
            lift = 0.08 * abs(ph) * env
        elif m == "dance":                                              # танец: качает бёдрами, руки по очереди вверх
            ph = math.sin(2 * math.pi * (t - a) / 0.8)
            B["torso"][2] = 14 * ph * env
            B["head"][1] += 10 * ph * env
            B["arm_l"][1] = (150 if ph > 0 else 30) * env
            B["arm_r"][1] = (-30 if ph > 0 else -150) * env
            lift = 0.12 * abs(math.sin(2 * math.pi * (t - a) / 0.4)) * env
    for k, (rx, ry, rz) in B.items():
        BODY[k].rotation_euler = (math.radians(rx), math.radians(ry), math.radians(rz))
    BODY["torso"].scale = (1, 1, squash * (1 + 0.012 * breath))
    hero_obj.location = (HX, HY, HZ + lift)


for f in range(FRAMES):
    u = f / FRAMES
    if MOVES:
        pose(f / 15)                                                    # камера стоит, героиня двигается
        root.location = (0, 0, 0.3 * math.sin(2 * math.pi * u))
    else:
        root.rotation_euler = (0, 0, 2 * math.pi * u)                  # облёт по кругу — петля
        root.location = (0, 0, 0.6 * math.sin(2 * math.pi * u * 2))    # остров чуть парит
        wave = math.sin(2 * math.pi * u * 6)
        pivot.rotation_euler = (0, math.radians(-150 + 25 * wave), 0)  # машет рукой
    for p, px, py, ph, sp in petals:
        k = (u * 3 * sp + ph) % 1.0                                     # периодично — петля сходится
        p.location = (px + 1.5 * math.sin(2 * math.pi * (k + ph)), py + 1.5 * math.cos(2 * math.pi * k), 26 - 22 * k)
        p.rotation_euler = (k * 9, k * 7, 0)
    bpy.context.view_layer.update()
    r.filepath = os.path.join(OUT, "v%03d.png" % f)
    bpy.ops.render.render(write_still=True)
print("ГОТОВО")
