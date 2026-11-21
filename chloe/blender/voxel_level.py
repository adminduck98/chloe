"""Blender без окна: воксельный 3D-уровень «внутри игры» в духе уютных сцен канала — всё строит код.

Земля из кубиков с травой, цветами и почвой; ямы, шипы, блок «?», монеты, столбик, портал; за полем — деревня
с домиками и сакурой, холмы-террасы и горы в дымке; лепестки в воздухе. Героиня Мия (hero3d.py) бежит, прыгает
и машет у портала — по плану уровня (chloe/level_plan.py): тот же план читает сборка ролика (счёт, надписи).

Запуск:  blender -b -P voxel_level.py -- OUT_DIR
     или python3.11 voxel_level.py -- OUT_DIR   (Blender как модуль: pip install bpy)
Переменные: LV_W, LV_H (размер кадра, по умолчанию 540×960), LV_FPS (15), LV_SAMPLES (16),
LV_FROM, LV_TO (какие кадры), LV_ONLY (через запятую — только эти кадры, для проверки).
Работает в Blender 3.6 … 5.x."""
import math
import os
import random
import sys

import bpy
import bmesh
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import level_plan as LP                                                 # noqa: E402

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.path.join(os.getcwd(), "level")
os.makedirs(OUT, exist_ok=True)
W, H = int(os.environ.get("LV_W", 540)), int(os.environ.get("LV_H", 960))
FPS = int(os.environ.get("LV_FPS", 15))
PLAN = LP.Plan()
SECONDS = PLAN.portal_t + 2.6
TOTAL = int(SECONDS * FPS)
F0, F1 = int(os.environ.get("LV_FROM", 0)), int(os.environ.get("LV_TO", TOTAL))
ONLY = [int(x) for x in os.environ.get("LV_ONLY", "").split(",") if x.strip()]
random.seed(11)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def lin(c):
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c)


def jit(c, k=0.04):
    d = random.uniform(-k, k)
    return tuple(min(1, max(0, v + d)) for v in c)


def mix(a, b, k):
    return tuple(x * (1 - k) + y * k for x, y in zip(a, b))


HAZE = hexc("c9c6ef")


def hazed(c, dist):
    """Воздушная перспектива — цвет дальних кубиков уходит в дымку неба."""
    return mix(c, HAZE, max(0.0, min(0.75, (dist - 14) / 120)))


C = {k: hexc(v) for k, v in {
    "g0": "3f8f3c", "g1": "5fb44a", "g2": "7fcb58", "g3": "a5e07a", "soil0": "5a3524", "soil1": "7a4a30", "soil2": "98603c",
    "stone0": "6d6a86", "stone1": "8f8bab", "stone2": "b3afcc", "gold0": "b5621d", "gold1": "f0a12a", "gold2": "ffd04a",
    "used0": "4a2c22", "used1": "6e4433", "wall": "f1e3cc", "wall2": "dcc8ab", "timber": "6b3d2a", "win": "ffd36b",
    "sak0": "e07aa6", "sak1": "f4a2c4", "sak2": "ffc8de", "sak3": "ffe4ef", "bark": "6b3d2a", "path": "eac28a",
    "terr0": "8aa86a", "terr1": "a8c47e", "terr2": "c9dc98", "sand": "dcae74", "lilac0": "8f86b0", "lilac1": "aaa2c8",
}.items()}
FLOWERS = [hexc(x) for x in ("ffe36b", "ff9fc8", "8fb8ff", "ffffff", "c48dff", "ffae5c")]
ROOFS = [hexc(x) for x in ("5a7fdb", "7a5cc4", "e8784a", "57a063", "cf5463", "6c7287")]

FACES = [((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
         ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
         ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]),
         ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
         ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
         ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)])]


def _input(node, *names):
    for n in names:
        if n in node.inputs:
            return node.inputs[n]
    return None


_MATS = {}


def vox_material(emit=0.0, rough=0.75, metal=0.0, key="vox"):
    """Цвет — из атрибута сетки (на каждой грани свой), скруглённые края кубиков."""
    key = "{}-{}-{}-{}".format(key, emit, rough, metal)
    if key in _MATS:
        return _MATS[key]
    m = bpy.data.materials.new(key)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "col"
    nt.links.new(attr.outputs["Color"], b.inputs["Base Color"])
    if emit:
        ec = _input(b, "Emission Color", "Emission")
        nt.links.new(attr.outputs["Color"], ec)
        es = _input(b, "Emission Strength")
        if es:
            es.default_value = emit
    bev = nt.nodes.new("ShaderNodeBevel")
    bev.inputs["Radius"].default_value = 0.04
    nt.links.new(bev.outputs["Normal"], b.inputs["Normal"])
    _MATS[key] = m
    return m


def flat_material(col, emit=0.0, rough=0.6, metal=0.0, name="flat"):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*lin(col), 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        _input(b, "Emission Color", "Emission").default_value = (*lin(col), 1)
        es = _input(b, "Emission Strength")
        if es:
            es.default_value = emit
    return m


def link(ob):
    scene.collection.objects.link(ob)
    return ob


def voxel_mesh(name, vox, size, origin=(0, 0, 0), mat=None):
    """vox: {(x,y,z): rgb} в целых клетках размера size. Только видимые грани, цвет на грань."""
    verts, faces, cols = [], [], []
    ox, oy, oz = origin
    for (x, y, z), c in vox.items():
        for (nx, ny, nz), quad in FACES:
            if (x + nx, y + ny, z + nz) in vox:
                continue
            i = len(verts)
            for qx, qy, qz in quad:
                verts.append(((x + qx) * size + ox, (y + qy) * size + oy, (z + qz) * size + oz))
            faces.append((i, i + 1, i + 2, i + 3))
            cols.append(lin(c))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ca = me.color_attributes.new("col", "FLOAT_COLOR", "CORNER")
    for poly, c in zip(me.polygons, cols):
        for li in poly.loop_indices:
            ca.data[li].color = (*c, 1.0)
    me.materials.append(mat or vox_material())
    return link(bpy.data.objects.new(name, me))


# ================================================================ земля уровня
V = 0.5                                                                  # кубик земли — полплитки
X0, X1 = -14, PLAN.length + 16
ground = {}
flowers = {}
for xi in range(int(X0 / V), int(X1 / V)):
    x = xi * V
    if not PLAN.solid(x + V / 2):
        for zi in (-15,):                                                # дно ямы — тёмное и глубоко
            for yi in range(-5, 7):
                ground[(xi, yi, zi)] = jit(mix(C["soil0"], (0.05, 0.03, 0.04), 0.6), 0.02)
        continue
    for yi in range(-5, 7):                                              # полоса земли: y от −2.5 до 3.5
        for zi in range(-14, 0):
            if zi == -1 and -2 <= yi <= 1:                                # песочная тропинка посередине — по ней бежит героиня
                c = random.choice((C["path"], C["path"], C["sand"], mix(C["path"], (1, 1, 1), 0.2)))
            elif zi == -1:
                c = random.choice((C["g1"], C["g1"], C["g2"], C["g2"], C["g3"], C["g0"]))
            elif zi == -2 and yi == -5:
                c = C["g0"]                                              # край травы спереди
            else:
                c = C["soil1"] if zi > -6 else C["soil0"]
                if random.random() < 0.12:
                    c = C["soil2"]
            ground[(xi, yi, zi)] = jit(c, 0.03)
        if random.random() < 0.3 and yi > -5 and not -2 <= yi <= 1:       # цветы и травинки на траве (не на тропинке)
            fc = random.choice(FLOWERS) if random.random() < 0.6 else C["g3"]
            flowers[(int(xi * 4 + random.randint(0, 3)), int(yi * 4 + random.randint(0, 3)), 0)] = fc
voxel_mesh("ground", ground, V)
voxel_mesh("flowers", flowers, 0.125, mat=vox_material(rough=0.5, key="flw"))

# шипы, столбик, блок «?», монеты, портал
steel = flat_material(hexc("c9cfe0"), rough=0.25, metal=0.85, name="steel")
for col, kind, n in PLAN.features:
    if kind == "spikes":
        bm = bmesh.new()
        for c in range(col, col + n):
            for k in range(2):
                for yy in (-0.9, 0.0, 0.9):
                    cx, cy = c + 0.25 + k * 0.5, yy
                    base = [bm.verts.new((cx + dx, cy + dy, 0)) for dx, dy in ((-0.22, -0.22), (0.22, -0.22), (0.22, 0.22), (-0.22, 0.22))]
                    tip = bm.verts.new((cx, cy, 0.75))
                    for i in range(4):
                        bm.faces.new((base[i], base[(i + 1) % 4], tip))
        me = bpy.data.meshes.new("spikes{}".format(col))
        bm.to_mesh(me)
        me.materials.append(steel)
        link(bpy.data.objects.new(me.name, me))
    elif kind == "pillar":
        vox = {}
        for xi in range(4):
            for yi in range(4):
                for zi in range(n * 4):
                    brick = ((zi // 2) + (xi // 2 if (zi // 2) % 2 else 0)) % 2
                    vox[(xi, yi, zi)] = jit(C["stone1"] if brick else C["stone0"], 0.03)
            vox[(xi, 0, n * 4)] = C["stone2"]
        voxel_mesh("pillar", vox, 0.25, (col, -0.5, 0))

QMARK = ["0110", "1001", "0010", "0100", "0000", "0100"]


def qblock(used):
    vox = {}
    S = 8
    for x in range(S):
        for y in range(S):
            for z in range(S):
                edge = (x in (0, S - 1)) + (y in (0, S - 1)) + (z in (0, S - 1)) >= 2
                if used:
                    c = C["used0"] if edge else C["used1"]
                else:
                    c = C["gold0"] if edge else C["gold1"]
                vox[(x, y, z)] = jit(c, 0.02)
    if not used:
        for r, row in enumerate(QMARK):                                  # «?» спереди и сзади
            for k, b in enumerate(row):
                if b == "1":
                    for y in (0, S - 1):
                        vox[(2 + k, y, 6 - r)] = C["gold2"]
    return vox


BLOCKS = []
for col, kind in PLAN.block:
    org = (col, -0.5, PLAN.block_z)
    gold = voxel_mesh("qblock", qblock(False), 0.125, org, mat=vox_material(emit=0.25, rough=0.4, metal=0.3, key="gold"))
    used = voxel_mesh("qblock_used", qblock(True), 0.125, org)
    BLOCKS.append((gold, used, org))

coin_mat = flat_material(hexc("ffc93d"), emit=0.6, rough=0.2, metal=1.0, name="coin")
COINS = []
for i, (cx, cz) in enumerate(PLAN.coins):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.32, radius2=0.32, depth=0.1)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "X"))
    me = bpy.data.meshes.new("coin{}".format(i))
    bm.to_mesh(me)
    me.materials.append(coin_mat)
    ob = link(bpy.data.objects.new(me.name, me))
    ob.location = (cx, 0, cz)
    COINS.append(ob)

# портал: светящееся кольцо, вихрь внутри, свет
px = PLAN.portal_x
bm = bmesh.new()
R, r, SEG, RING = 1.0, 0.13, 40, 10
rows = []
for i in range(SEG):
    a = i / SEG * math.tau
    row = []
    for j in range(RING):
        b = j / RING * math.tau
        rr = R + r * math.cos(b)
        row.append(bm.verts.new((rr * math.cos(a) * 0.62, r * math.sin(b), rr * math.sin(a))))
    rows.append(row)
for i in range(SEG):
    for j in range(RING):
        bm.faces.new((rows[i][j], rows[(i + 1) % SEG][j], rows[(i + 1) % SEG][(j + 1) % RING], rows[i][(j + 1) % RING]))
me = bpy.data.meshes.new("portal_ring")
bm.to_mesh(me)
me.materials.append(flat_material(hexc("7fe9ff"), emit=6.0, name="portal_ring"))
ring = link(bpy.data.objects.new("portal_ring", me))
ring.location = (px, 0.2, 1.15)
swirl = bpy.data.materials.new("swirl")
swirl.use_nodes = True
nt = swirl.node_tree
b = nt.nodes["Principled BSDF"]
noise = nt.nodes.new("ShaderNodeTexWave")
noise.wave_type = "RINGS"
noise.inputs["Scale"].default_value = 3.0
noise.inputs["Distortion"].default_value = 6.0
mapn = nt.nodes.new("ShaderNodeMapping")
coord = nt.nodes.new("ShaderNodeTexCoord")
nt.links.new(coord.outputs["Object"], mapn.inputs["Vector"])
nt.links.new(mapn.outputs["Vector"], noise.inputs["Vector"])
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (*lin(hexc("1a4fb0")), 1)
ramp.color_ramp.elements[1].color = (*lin(hexc("bff8ff")), 1)
nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
nt.links.new(ramp.outputs["Color"], _input(b, "Emission Color", "Emission"))
_input(b, "Emission Strength").default_value = 3.0
bpy.ops.mesh.primitive_circle_add(vertices=32, radius=1.0, fill_type="NGON", location=(px, 0.2, 1.15), rotation=(math.pi / 2, 0, 0))
disc = bpy.context.active_object
disc.scale = (0.6, 1.0, 1.0)
disc.data.materials.append(swirl)
plight = bpy.data.lights.new("portal_light", "POINT")
plight.energy = 220
plight.color = (0.45, 0.9, 1.0)
plight.shadow_soft_size = 0.6
pl = link(bpy.data.objects.new("portal_light", plight))
pl.location = (px, -0.8, 1.2)

# ================================================================ фон: луг, деревня, сакура, террасы, горы
meadow = {}
for xi in range(int(X0 - 30), int(X1 + 40)):
    for yi in range(4, 34):
        c = random.choice((C["g1"], C["g2"], C["g2"], C["g3"]))
        if random.random() < 0.08:
            c = random.choice(FLOWERS)
        meadow[(xi, yi, -1)] = hazed(jit(c, 0.03), yi)
        if yi == 4:
            for zi in range(-8, -1):                                     # уступ луга виден из-за дорожки
                meadow[(xi, yi, zi)] = hazed(jit(C["soil1"], 0.03), yi)
voxel_mesh("meadow", meadow, 1.0, (0, 0, -1.0))                          # луг на кубик ниже дорожки уровня


def house(x0, y0, w, d, h, roof, seed):
    rnd = random.Random(seed)
    vox = {}
    dist = y0 * 0.5 + 8
    for x in range(w):
        for y in range(d):
            for z in range(h):
                c = C["wall"]
                if x in (0, w - 1) or z == h - 1:
                    c = C["timber"] if rnd.random() < 0.7 else C["wall2"]
                if y == 0 and 1 < x < w - 2 and z in (3, 4, 8, 9) and (x - 2) % 4 in (0, 1) and z < h - 2:
                    c = C["win"]
                vox[(x, y, z)] = hazed(jit(c, 0.02), dist)
        if y0 >= 0:
            pass
    rh = (w + 1) // 2 + 1
    for k in range(rh):                                                   # двускатная крыша ступеньками
        for x in range(-1 + k, w + 1 - k):
            for y in range(-1, d + 1):
                vox[(x, y, h + k)] = hazed(jit(roof if (k + y) % 2 else mix(roof, (0, 0, 0), 0.15), 0.02), dist)
    cx = rnd.randint(1, max(1, w - 3))
    for z in range(h + 1, h + rh + 1):
        vox[(cx, d // 2, z)] = hazed(C["timber"], dist)
    for x in range(2, w - 2):                                             # ящики с цветами под окнами
        if (x - 2) % 4 in (0, 1):
            vox[(x, -1, 2)] = hazed(rnd.choice(FLOWERS), dist)
    return vox


def sakura(seed, size):
    rnd = random.Random(seed)
    vox = {}
    for z in range(int(size * 1.2)):
        vox[(0, 0, z)] = C["bark"]
        vox[(1, 0, z)] = C["bark"]
    blobs = [(rnd.uniform(-size * 0.6, size * 0.6), rnd.uniform(-size * 0.5, size * 0.5), size * 1.3 + rnd.uniform(-1, size * 0.5),
              size * rnd.uniform(0.5, 0.75)) for _ in range(6)]
    for bx, by, bz, br in blobs:
        for x in range(int(bx - br), int(bx + br) + 1):
            for y in range(int(by - br), int(by + br) + 1):
                for z in range(int(bz - br), int(bz + br) + 1):
                    d2 = (x - bx) ** 2 + (y - by) ** 2 + (z - bz) ** 2
                    if d2 <= br * br * rnd.uniform(0.75, 1.0):
                        top = (z - bz) / br
                        c = C["sak2"] if top > 0.3 else C["sak1"] if top > -0.4 else C["sak0"]
                        if rnd.random() < 0.08:
                            c = C["sak3"]
                        vox[(x, y, z)] = c
    return vox


vill = {}
rnd = random.Random(5)
for row, (yb, xstep) in enumerate(((11, 11), (21, 13))):                  # два ряда: ближний и дальний
    x = X0 - 10 + row * 5
    while x < X1 + 30:
        if rnd.random() < 0.6:
            w, d, h = rnd.choice((7, 9, 11)), rnd.choice((6, 8)), rnd.choice((7, 10, 12))
            vox = house(0, yb, w, d, h, rnd.choice(ROOFS), rnd.random())
            sc = 0.5
            for (vx, vy, vz), c in vox.items():
                vill[(int(x / sc) + vx, int(yb / sc) + vy, vz)] = c
            x += w * sc + rnd.uniform(2, 5)
        else:
            size = rnd.uniform(4, 6)
            vox = sakura(rnd.random(), size)
            for (vx, vy, vz), c in vox.items():
                vill[(int(x / 0.5) + vx, int((yb + 1.5) / 0.5) + vy, vz)] = hazed(c, yb * 0.5 + 8)
            x += size * 0.9 + rnd.uniform(1, 3)
voxel_mesh("village", vill, 0.5, (0, 0, 0), mat=vox_material(emit=0.0, key="vill"))

hills = {}
for band, (yb, amp, cols) in enumerate(((44, 10, ("terr1", "terr2")), (62, 16, ("sand", "terr2")), (84, 22, ("terr0", "terr1")))):
    for xi in range(int((X0 - 80) / 2), int((X1 + 120) / 2)):
        hgt = int(amp * (0.55 + 0.45 * math.sin(xi * 0.07 + band * 2.1) * math.cos(xi * 0.023 + band)) / 2)
        for yi in range(int(yb / 2), int(yb / 2) + 6):
            for zi in range(0, max(1, hgt - (yi - int(yb / 2)) // 2)):
                c = C[cols[(zi // 2) % 2]]
                hills[(xi, yi, zi)] = hazed(jit(c, 0.02), yb + 20)
voxel_mesh("hills", hills, 2.0, (0, 0, -1.0))
mountains = {}
for xi in range(int((X0 - 200) / 6), int((X1 + 260) / 6)):               # горы — сиреневые, в дымке
    hgt = int(4 + 3 * math.sin(xi * 0.21) + 2 * math.sin(xi * 0.53 + 1))
    for zi in range(hgt):
        for yi in (26, 27):
            mountains[(xi, yi, zi)] = hazed(C["lilac1" if zi > hgt - 2 else "lilac0"], 150)
voxel_mesh("mountains", mountains, 6.0, (0, 0, -2.0))

# лепестки
petal_mat = flat_material(hexc("ffb3cf"), emit=1.2, rough=0.5, name="petal")
PETALS = []
for i in range(70):
    bpy.ops.mesh.primitive_plane_add(size=0.16)
    p = bpy.context.active_object
    p.data.materials.append(petal_mat)
    PETALS.append((p, random.uniform(-6, 14), random.uniform(-3, 8), random.uniform(0, 9), random.uniform(0.6, 1.4), random.random() * 6))

# ================================================================ героиня
import hero3d                                                          # noqa: E402

ARM, _ = hero3d.build(height=LP.HERO_H)
YAW = math.radians(34)                                                  # вполоборота: бежит вправо, лицо видно


def rot(bone, axis, deg):
    pb = ARM.pose.bones[bone]
    e = pb.rotation_euler
    i = "XYZ".index(axis)
    e[i] += math.radians(deg)
    pb.rotation_euler = e


def hero_pose(t):
    x, lift, air, ph = PLAN.hero(t)
    at_portal = x >= PLAN.portal_x - 1e-6
    hero3d.pose_at(ARM, t, [], base_loc=Vector((x, 0, lift + LP.HERO_H / 2)), base_yaw=YAW if not at_portal else 0.0)
    if t < LP.WAIT:
        return x, lift
    if at_portal:                                                       # у портала — повернулась к зрителю и машет
        d = t - PLAN.portal_t
        rot("upper_arm.R", "Z", -125)
        rot("fore_arm.R", "Z", -(35 + 30 * math.sin(d * 14)))
        rot("upper_arm.L", "Z", 40)
        ARM.location.z += 0.25 * abs(math.sin(d * 6)) * max(0, 1 - d)
        return x, lift
    if air:                                                             # прыжок: колени к груди, руки вверх, волосы вверх
        up = math.sin(math.pi * ph)
        rot("thigh.L", "X", -70 * up)
        rot("shin.L", "X", 90 * up)
        rot("thigh.R", "X", -25 * up)
        rot("shin.R", "X", 60 * up)
        rot("upper_arm.L", "Z", 120 * up)
        rot("upper_arm.R", "Z", -120 * up)
        rot("hair", "X", -35 * up)
        return x, lift
    ph = math.sin(2 * math.pi * (t - LP.WAIT) / 0.46)                   # бег: ноги и руки в противоход
    for s, sg in ((".L", 1), (".R", -1)):
        rot("thigh" + s, "X", -48 * ph * sg)
        rot("shin" + s, "X", 15 + 70 * max(0.0, -ph * sg))
        rot("upper_arm" + s, "X", -8 + 24 * ph * sg)
        rot("fore_arm" + s, "Z", 45 if s == ".L" else -45)
    rot("spine", "X", -10)
    rot("hair", "X", 15)
    ARM.location.z += 0.05 * abs(ph)
    return x, lift


# ================================================================ свет, небо, камера, рендер
sun = bpy.data.lights.new("sun", "SUN")
sun.energy = 3.6
sun.angle = math.radians(4)
sun.color = (1.0, 0.92, 0.82)
so = link(bpy.data.objects.new("sun", sun))
so.rotation_euler = (math.radians(52), math.radians(0), math.radians(-28))
world = bpy.data.worlds.new("w")
world.use_nodes = True
wn = world.node_tree
sky = wn.nodes.new("ShaderNodeTexSky")
for kind in ("NISHITA", "MULTIPLE_SCATTERING", "HOSEK_WILKIE"):        # Blender 3–4: NISHITA, 5: MULTIPLE_SCATTERING
    try:
        sky.sky_type = kind
        break
    except TypeError:
        continue
if hasattr(sky, "sun_elevation"):
    sky.sun_elevation = math.radians(38)
    sky.sun_rotation = math.radians(200)
if hasattr(sky, "sun_disc"):
    sky.sun_disc = False
tint = wn.nodes.new("ShaderNodeMixRGB")                                  # пастель: небо смешано с сиреневым
tint.blend_type = "MIX"
tint.inputs["Fac"].default_value = 0.6
tint.inputs["Color2"].default_value = (*lin(hexc("7f99ee")), 1)
wn.links.new(sky.outputs["Color"], tint.inputs["Color1"])
wn.links.new(tint.outputs["Color"], wn.nodes["Background"].inputs["Color"])
wn.nodes["Background"].inputs["Strength"].default_value = 1.0
scene.world = world

cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 30
cam_data.dof.use_dof = True
cam_data.dof.aperture_fstop = 2.2                                       # мягкая глубина резкости — фон чуть размыт
cam = link(bpy.data.objects.new("cam", cam_data))
scene.camera = cam


def place_camera(t):
    cx = LP.smooth_cam(PLAN, t)
    if os.environ.get("LV_CLOSE"):                                      # проверка героини крупно
        hx = PLAN.hero(t)[0]
        target = Vector((hx, 0, 1.3))
        cam.location = Vector((hx + 1.5, -6.0, 2.0))
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        return
    target = Vector((cx, 4.0, 2.3))
    cam.location = Vector((cx, -11.5, 5.2))
    hx = PLAN.hero(t)[0]
    cam_data.dof.focus_distance = (cam.location - Vector((hx, 0, 1.3))).length
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()


r = scene.render
r.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = int(os.environ.get("LV_SAMPLES", 16))
scene.cycles.max_bounces = 3
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.05
r.use_persistent_data = True                                            # сцена между кадрами не перестраивается — в разы быстрее
try:
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
except (AttributeError, TypeError):
    pass
r.resolution_x, r.resolution_y = W, H
r.image_settings.file_format = "PNG"
for vt, look in (("AgX", "AgX - Punchy"), ("Filmic", "Medium High Contrast")):
    try:
        scene.view_settings.view_transform = vt
        scene.view_settings.look = look
        break
    except TypeError:
        continue

EVENTS = PLAN.events(FPS, SECONDS)
frames = ONLY or range(F0, min(F1, TOTAL))
for f in frames:
    t = f / FPS
    ev = EVENTS[min(f, len(EVENTS) - 1)]
    hero_pose(t)
    place_camera(t)
    for i, ob in enumerate(COINS):                                       # монеты крутятся; собранная — взлетает и тает
        cx, cz = PLAN.coins[i]
        got = ev["taken"].get(i)
        ob.rotation_euler = (0, 0, t * 4 + i)
        if got is None:
            ob.location = (cx, 0, cz + 0.06 * math.sin(t * 3 + i))
            ob.scale = (1, 1, 1)
        else:
            k = (f - got) / FPS / 0.3
            ob.location = (cx, 0, cz + 0.8 * min(1, k))
            s = max(0.0, 1 - k)
            ob.scale = (s, s, s)
    for gold, used, org in BLOCKS:
        hit = ev["block_hit"]
        dz = 0.35 * LP.bump(hit, f, FPS)
        gold.hide_render = hit is not None and f >= hit
        used.hide_render = not gold.hide_render
        gold.location.z = used.location.z = dz
    disc.rotation_euler = (math.pi / 2, t * 1.8, 0)
    open_k = LP.ease((t - 0.8) / 0.8)
    ring.scale = (max(0.02, open_k), 1, max(0.02, open_k))
    disc.scale = (0.6 * max(0.02, open_k), max(0.02, open_k), 1)
    for p, x0, y0, z0, sp, ph in PETALS:                                 # лепестки летят вокруг камеры
        cx = LP.smooth_cam(PLAN, t)
        p.location = (cx + ((x0 - t * 0.9 * sp) % 20) - 8, y0, (z0 - t * 0.7 * sp) % 9 + math.sin(t * 2 + ph) * 0.2)
        p.rotation_euler = (t * 2 + ph, t * 1.5, ph)
    scene.render.filepath = os.path.join(OUT, "f_{:04d}.png".format(f))
    bpy.ops.render.render(write_still=True)
print("LEVEL_FRAMES", TOTAL, FPS)
