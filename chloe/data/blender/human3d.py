"""Хлоя: реалистичный 3D-человек без лица в одежде повторяет движение, выученное с видео (3D-скелет MediaPipe).

Запускает chloe/human3d.py так: blender -b -P human3d.py -- --move m.json --out папка [--frames all|1,5,9]
  [--view 34|filmed|side|front] [--size 960x540] [--outfit male_casualsuit04] [--shoes shoes01]
  [--props '[{"at": 0, "prop": "rifle"}, {"at": 0.46, "prop": "pistol"}]'] [--cloth 1]

Тело и одежда — MPFB (дополнение MakeHuman для Blender, GPL) и бесплатные ассеты MakeHuman (CC0): нормальная анатомия,
53 кости. Голова модели скрыта — вместо неё гладкая голова манекена (лица нет). Каждая кость смотрит на свою точку
3D-скелета; горизонт выровнен (телефон снимал с наклоном), ступни — на полу. Футболка — ткань с физикой: закреплена
на плечах, подол свободный, тело — препятствие. Кадры — PNG в папку --out (видео из них собирает Хлоя).
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector

from bl_ext.user_default.mpfb.services.humanservice import HumanService
from bl_ext.user_default.mpfb.services.locationservice import LocationService

ap = argparse.ArgumentParser()
ap.add_argument("--move", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--frames", default="all")
ap.add_argument("--view", default="34")
ap.add_argument("--size", default="960x540")
ap.add_argument("--outfit", default="male_casualsuit04")
ap.add_argument("--shoes", default="shoes01")
ap.add_argument("--props", default="[]")
ap.add_argument("--cloth", default="1")
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])
move = json.load(open(args.move))
out_dir = args.out
frames_arg = args.frames
frames_arg_list = [int(x) for x in frames_arg.split(",")] if frames_arg != "all" else []
view = args.view
W, H = (int(x) for x in args.size.split("x"))
OUTFIT, SHOES = args.outfit, args.shoes
PROPS = sorted(json.loads(args.props), key=lambda p: float(p.get("at", 0)))
body = move["body3d"]
n = len(body)

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
sc = bpy.context.scene

# --- человек: мужчина, спортивный, без лица ---
macro = {"gender": 1.0, "age": 0.45, "muscle": 0.65, "weight": 0.5, "proportions": 0.6, "height": 0.55, "cupsize": 0.5,
         "firmness": 0.5, "race": {"asian": 0.2, "caucasian": 0.6, "african": 0.2}}
bm = HumanService.create_human(scale=0.1, macro_detail_dict=macro)
rig = HumanService.add_builtin_rig(bm, "game_engine")
data_dir = LocationService.get_user_data()
for name, kind in ((OUTFIT, "Clothes"), (SHOES, "Clothes")):
    path = os.path.join(data_dir, "clothes", name, name + ".mhclo")
    if os.path.exists(path):
        HumanService.add_mhclo_asset(path, bm, asset_type=kind, subdiv_levels=1)
    else:
        print("НЕТ АССЕТА", path, flush=True)

# лица нет: голова сглажена и приведена к округлой форме манекена (до костей — в позе покоя)
if "head" in bm.vertex_groups:                                     # голова модели скрыта (лицо не рисуется)
    mk = bm.modifiers.new("NoFace", "MASK")
    mk.vertex_group, mk.invert_vertex_group, mk.threshold = "head", True, 0.5
sub = bm.modifiers.new("Subdiv", "SUBSURF")
sub.levels, sub.render_levels = 0, 1
skin = bpy.data.materials.new("Skin")
skin.use_nodes = True
b = skin.node_tree.nodes["Principled BSDF"]
b.inputs["Base Color"].default_value = (0.72, 0.52, 0.42, 1)
b.inputs["Roughness"].default_value = 0.55
for k in ("Subsurface Weight", "Subsurface"):
    if k in b.inputs:
        b.inputs[k].default_value = 0.15
        break
bm.data.materials.clear()
bm.data.materials.append(skin)
for p in bm.data.polygons:
    p.material_index = 0
    p.use_smooth = True

# гладкая голова-яйцо манекена на кости головы
hb = rig.data.bones["head"]
h0, h1 = rig.matrix_world @ hb.head_local, rig.matrix_world @ hb.tail_local
bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, segments=48, ring_count=32, location=h0 + (h1 - h0) * 0.55)
egg = bpy.context.object
egg.name = "HeadEgg"
egg.scale = (0.088, 0.105, 0.122)
bpy.ops.object.shade_smooth()
egg.data.materials.append(skin)
mw = egg.matrix_world.copy()
egg.parent, egg.parent_type, egg.parent_bone = rig, "BONE", "head"
egg.matrix_world = mw

# --- данные MediaPipe → координаты Blender, в масштабе этого тела ---
rest_bone = {b.name: b for b in rig.data.bones}
rw = rig.matrix_world


def rest_head(name):
    return rw @ rest_bone[name].head_local


def rest_tail(name):
    return rw @ rest_bone[name].tail_local


rig_leg = (rest_tail("thigh_l") - rest_head("thigh_l")).length + (rest_tail("calf_l") - rest_head("calf_l")).length


def raw(fr, k):
    if k == "hip":
        return Vector((0, 0, 0))
    x, y, z = fr[k]
    return Vector((x, z, -y))


legs = sorted(((raw(fr, "kn2") - raw(fr, "hip2")).length + (raw(fr, "foot2") - raw(fr, "kn2")).length) for fr in body)
S = rig_leg / legs[len(legs) // 2]
KEYS = ("hip", "neck", "head", "sh1", "sh2", "el1", "el2", "hand1", "hand2", "fi1", "fi2", "hip1", "hip2", "kn1", "kn2",
        "foot1", "foot2", "toe1", "toe2")
ALL = [{k: raw(fr, k) * S for k in KEYS} for fr in body]
# горизонт: телефон снимал с наклоном — средняя ось тела (от середины стоп к середине плеч) становится вертикалью
axis = sum((((p["sh1"] + p["sh2"]) / 2 - (p["foot1"] + p["foot2"]) / 2) for p in ALL), Vector()).normalized()
level = axis.rotation_difference(Vector((0, 0, 1))).to_matrix()
ALL = [{k: level @ v for k, v in p.items()} for p in ALL]
# пол — под нижней ступнёй каждого кадра (глубина MediaPipe шумит; плавно, чтобы не дрожало)
lows = [min(p[k].z for k in ("foot1", "foot2", "toe1", "toe2")) for p in ALL]
lows = [sum(lows[max(0, i - 3):i + 4]) / len(lows[max(0, i - 3):i + 4]) for i in range(len(lows))]
floor = 0.0
ankle_h = rest_head("foot_l").z                                    # щиколотка над полом у этого тела
face = math.radians(float(move.get("face3d", -90)))

# --- кости смотрят на свои точки (1 — правая сторона человека, 2 — левая) ---
TRACK = {"clavicle_r": "sh1", "upperarm_r": "el1", "lowerarm_r": "hand1", "hand_r": "fi1",
         "clavicle_l": "sh2", "upperarm_l": "el2", "lowerarm_l": "hand2", "hand_l": "fi2",
         "thigh_r": "kn1", "calf_r": "foot1", "foot_r": "toe1",
         "thigh_l": "kn2", "calf_l": "foot2", "foot_l": "toe2",
         "spine_01": "neck", "spine_02": "neck", "spine_03": "neck", "neck_01": "headup"}
neck_rest = (rest_tail("neck_01") - rest_head("neck_01")).normalized()
head_avg = sum((p["head"] - p["neck"] for p in ALL), Vector()).normalized()
neck_fix = head_avg.rotation_difference(neck_rest).to_matrix()   # средняя поза головы с видео = поза покоя модели
targets = {}
for k in KEYS + ("headup",):
    e = bpy.data.objects.new("T_" + k, None)
    sc.collection.objects.link(e)
    targets[k] = e
for bone, k in TRACK.items():
    pb = rig.pose.bones.get(bone)
    if pb:
        c = pb.constraints.new("DAMPED_TRACK")
        c.target = targets[k]
pelvis0 = rest_head("pelvis") - rig.location                        # таз относительно начала скелета
for f, p in enumerate(ALL, 1):
    lift = Vector((0, 0, -lows[f - 1] + ankle_h * 0.35))
    across = p["hip2"] - p["hip1"]                                  # справа налево у человека
    yaw = math.atan2(across.y, across.x)                            # у тела в покое левое бедро — по +X
    rig.rotation_euler = (0, 0, yaw)
    rig.keyframe_insert("rotation_euler", frame=f)
    off = Matrix.Rotation(yaw, 3, "Z") @ pelvis0
    rig.location = p["hip"] + lift - off
    rig.keyframe_insert("location", frame=f)
    for k, e in targets.items():
        e.location = (p["neck"] + neck_fix @ (p["head"] - p["neck"]) if k == "headup" else p[k]) + lift
        e.keyframe_insert("location", frame=f)

# --- оружие в руках по времени (PROPS: [{at: доля движения, prop: rifle|pistol|null}]) ---


def prop_at(f):
    cur = None
    for p in PROPS:
        if (f - 1) / max(1, n - 1) >= float(p.get("at", 0)):
            cur = p.get("prop")
    return cur


gm = bpy.data.materials.new("Gun")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.05, 0.05, 0.06, 1)
gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.35
gm.node_tree.nodes["Principled BSDF"].inputs["Metallic"].default_value = 0.6


def box(size, loc, parent):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.scale = size
    o.data.materials.append(gm)
    o.parent = parent
    return o


def gun(kind):
    root = bpy.data.objects.new(kind, None)
    sc.collection.objects.link(root)
    if kind == "rifle":
        for size, loc in (((0.045, 0.2, 0.09), (0, -0.14, 0.03)), ((0.05, 0.36, 0.07), (0, 0.13, 0.05)),
                          ((0.045, 0.2, 0.055), (0, 0.38, 0.045)), ((0.02, 0.18, 0.02), (0, 0.56, 0.05)),
                          ((0.035, 0.05, 0.13), (0, 0.17, -0.04)), ((0.035, 0.04, 0.1), (0, 0.0, -0.03)),
                          ((0.02, 0.1, 0.025), (0, 0.12, 0.1))):
            box(size, loc, root)
    else:
        box((0.04, 0.22, 0.055), (0, 0.08, 0.05), root)
        box((0.038, 0.06, 0.14), (0, -0.005, -0.025), root)
    return root


rifle, pistol = gun("rifle"), gun("pistol")
g_at, g_to, p_at, p_to = (bpy.data.objects.new(nm, None) for nm in ("GripAt", "GripTo", "PistolAt", "PistolTo"))
for e in (g_at, g_to, p_at, p_to):
    sc.collection.objects.link(e)
for root, at, to in ((rifle, g_at, g_to), (pistol, p_at, p_to)):
    c1 = root.constraints.new("COPY_LOCATION")
    c1.target = at
    c2 = root.constraints.new("DAMPED_TRACK")
    c2.target, c2.track_axis = to, "TRACK_Y"
fwd = Vector((math.cos(face), math.sin(face), 0))
for f, p in enumerate(ALL, 1):
    lift = Vector((0, 0, -lows[f - 1] + ankle_h * 0.35))
    h1, h2 = p["hand1"], p["hand2"]
    grip, sup = (h1, h2) if (h1 - p["sh1"]).length <= (h2 - p["sh2"]).length else (h2, h1)
    d = sup - grip
    if d.length < 0.12 or d.normalized().dot(fwd) < 0.2 or abs(d.normalized().z) > 0.6:
        d = fwd
    g_at.location, g_to.location = grip + lift, grip + d.normalized() + lift
    front = h1 if (h1 - p["hip"]).dot(fwd) >= (h2 - p["hip"]).dot(fwd) else h2
    fi = p["fi1"] if front is h1 else p["fi2"]
    p_at.location = front + lift
    p_to.location = front + ((fi - front).normalized() if (fi - front).length > 0.01 else fwd) + lift
    for e in (g_at, g_to, p_at, p_to):
        e.keyframe_insert("location", frame=f)
    held = prop_at(f)
    for o, on in ((rifle, held == "rifle"), (pistol, held == "pistol")):
        for part in [o] + list(o.children):
            part.hide_render = not on
            part.keyframe_insert("hide_render", frame=f)

# --- пол, свет, мир, камера ---
bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, 0))
fm = bpy.data.materials.new("Floor")
fm.use_nodes = True
fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.16, 0.17, 0.2, 1)
fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.8
bpy.context.object.data.materials.append(fm)
bpy.ops.object.light_add(type="AREA", location=(-2.5, -3.0, 4.0))
key = bpy.context.object
key.data.energy, key.data.size = 1000, 3.0
key.rotation_euler = (math.radians(50), 0, math.radians(-40))
bpy.ops.object.light_add(type="AREA", location=(3.0, 2.5, 2.5))
rim = bpy.context.object
rim.data.energy, rim.data.size = 600, 2.0
rim.rotation_euler = (math.radians(-60), 0, math.radians(140))
rim.data.color = (0.6, 0.75, 1.0)
world = bpy.data.worlds.new("W")
sc.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.05, 0.055, 0.08, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.7
fx, fy = math.cos(face), math.sin(face)
side = {"filmed": None, "34": 55.0, "side": 90.0, "front": 0.0}[view]
if side is None:
    cam_dir = Vector((0, -1, 0))
else:
    a = math.atan2(fy, fx) - math.radians(side)
    cam_dir = Vector((math.cos(a), math.sin(a), 0))
bpy.ops.object.camera_add(location=(cam_dir * 4.8) + Vector((0, 0, 1.25)))
cam = bpy.context.object
cam.data.lens = 50
aim = bpy.data.objects.new("Aim", None)
sc.collection.objects.link(aim)
aim.location = (0, 0, 0.95)
tc = cam.constraints.new("TRACK_TO")
tc.target = aim
tc.track_axis, tc.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
sc.camera = cam
sc.frame_start, sc.frame_end = 1, n
sc.render.fps = move.get("fps", 25)
sc.render.engine = "BLENDER_EEVEE"
try:
    sc.eevee.taa_render_samples = 16
except Exception:
    pass
sc.render.resolution_x, sc.render.resolution_y = W, H
# --- физика ткани: футболка свободна у подола, джинсы и плечи закреплены, тело — препятствие ---
PHYS = args.cloth == "1"
suit = next((o for o in bpy.data.objects if o.type == "MESH" and OUTFIT in o.name), None)
if PHYS and suit:
    me = suit.data
    gidx = {g.index: g.name for g in suit.vertex_groups}
    zs = [(suit.matrix_world @ v.co).z for v in me.vertices]
    waist = (rig.matrix_world @ rig.data.bones["spine_01"].head_local).z
    pin = suit.vertex_groups.new(name="pin")
    for v, z in zip(me.vertices, zs):
        legw = sum(g.weight for g in v.groups if gidx[g.group].startswith(("thigh", "calf", "foot", "ball")))
        if legw > 0.2:
            w = 1.0                                                    # джинсы — по ногам
        else:
            w = max(0.0, min(1.0, (z - waist) / 0.28))                # футболка: от груди вниз — свободнее
        pin.add([v.index], w, "REPLACE")
    cl = suit.modifiers.new("Cloth", "CLOTH")
    suit.modifiers.move(list(suit.modifiers).index(cl), 1)             # после костей, до сглаживания
    st = cl.settings
    st.quality, st.mass, st.air_damping = 6, 0.2, 1.0
    st.tension_stiffness, st.compression_stiffness, st.shear_stiffness, st.bending_stiffness = 12, 12, 6, 0.3
    st.vertex_group_mass = "pin"
    st.pin_stiffness = 1.0
    cs = cl.collision_settings
    cs.use_collision, cs.distance_min, cs.use_self_collision = True, 0.006, False
    cl.point_cache.frame_start, cl.point_cache.frame_end = 1, n
    col = bm.modifiers.new("Collision", "COLLISION")
    bm.collision.thickness_outer = 0.008
    t0 = time.time()
    for f in range(1, (max(frames_arg_list) if frames_arg != "all" else n) + 1):   # ткань считается кадр за кадром
        sc.frame_set(f)
    print("ТКАНЬ посчитана за %.0f с" % (time.time() - t0), flush=True)

frames = list(range(1, n + 1)) if frames_arg == "all" else frames_arg_list
sc.render.use_persistent_data = True                                # сцена не собирается заново каждый кадр
if frames == list(range(frames[0], frames[-1] + 1)):                 # подряд — одним заходом, как анимация
    done = {"n": 0}

    def _post(scene, *_):
        done["n"] += 1
        print("КАДР", done["n"], len(frames), flush=True)
    bpy.app.handlers.render_write.append(_post)
    sc.frame_start, sc.frame_end = frames[0], frames[-1]
    sc.render.filepath = f"{out_dir}/f####"
    sc.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(animation=True)
else:
    for i, f in enumerate(frames, 1):
        sc.frame_set(f)
        sc.render.filepath = f"{out_dir}/f{f:04d}.png"
        bpy.ops.render.render(write_still=True)
        print("КАДР", i, len(frames), flush=True)
print("ГОТОВО", len(frames), flush=True)
