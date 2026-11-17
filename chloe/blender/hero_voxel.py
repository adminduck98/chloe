"""Героиня Мия из вокселей — строит код в Blender, без нейросетей. Спереди — цвета утверждённого рисунка
(assets/heroine/source.png: стоит прямо, руки отведены), по ячейкам 20×20 пикселей; объём, бока и спина — по правилам
частей тела (волосы с голубыми кончиками, наушники с голубыми кольцами, худи, шорты, гольфы, кроссовки).
Каждый кубик принадлежит одной кости — героиня двигается частями, как кукла из кубиков.
Модель: рост 1, лицом к −Y, ноги на z = −0.5, левая рука персонажа — +X (как BONES в hero3d.py)."""
import os

import bpy
import numpy as np

SRC = os.path.join(os.path.dirname(__file__), "..", "assets", "heroine", "source.png")
TOP, FOOT, MID = 168, 1460, 465            # разметка source.png: макушка, подошвы, середина
CELL = 20                                  # пикселей рисунка на кубик (≈ 65 кубиков в высоту)
ARM_L = [(625, 640), (625, 835), (835, 930), (905, 905), (905, 820), (870, 790)]   # на рисунке справа — левая рука
ARM_R = [(300, 640), (300, 835), (95, 930), (25, 905), (25, 820), (60, 790)]
CUPS = [(228, 300, 375, 520), (630, 702, 375, 520)]          # наушники: x0, x1, y0, y1 (пиксели)
NAVY, CYAN = (0.10, 0.13, 0.33), (0.30, 0.85, 1.0)
HAIR_TOP, HAIR_TIP = (0.93, 0.94, 0.98), (0.45, 0.70, 1.0)
HOOD, TRIM = (0.95, 0.96, 0.99), (0.40, 0.70, 0.98)
# глубина частей (y спереди, y сзади) в долях роста
DEPTH = {"head": (-0.15, 0.13), "cup": (-0.065, 0.065), "torso": (-0.085, 0.085), "hips": (-0.085, 0.085),
         "arm": (-0.05, 0.05), "leg": (-0.05, 0.05), "shoe": (-0.075, 0.055), "hair_side": (-0.02, 0.11)}


def _inside(poly, x, y):
    n, c = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-9) + x1:
            c = not c
    return c


def _image():
    img = bpy.data.images.load(os.path.abspath(SRC))
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[::-1, :, :3]                  # Blender хранит снизу вверх


def _label(px, py):
    """Часть тела в точке рисунка (центр ячейки)."""
    if any(x0 <= px < x1 and y0 <= py < y1 for x0, x1, y0, y1 in CUPS):
        return "cup"
    if _inside(ARM_L, px, py):
        return "arm.L"
    if _inside(ARM_R, px, py):
        return "arm.R"
    if py < 615:
        return "head"
    if py < 1010:
        return "torso" if 300 <= px <= 630 else "hair_side"
    if py < 1075:
        return "hips"
    return "shoe" if py > 1380 else "leg"


def _bone(label, x, z):
    side = ".L" if x > 0 else ".R"
    if label in ("head", "cup"):
        return "head"
    if label == "hair_side" or label == "hair_back":
        return "hair"
    if label.startswith("arm"):
        return ("upper_arm" if abs(x) < 0.215 else "fore_arm") + label[3:]
    if label == "torso":
        return "spine"
    if label == "hips":
        return "hips"
    return ("thigh" if z > -0.35 else "shin") + side


def _hair(z):
    """Цвет волос по высоте: белые сверху, к кончикам голубые (ступенями, как у вокселей)."""
    k = min(1.0, max(0.0, (0.05 - z) / 0.3))
    k = round(k * 4) / 4
    return tuple(a * (1 - k) + b * k for a, b in zip(HAIR_TOP, HAIR_TIP))


def voxels():
    """{(i, j, k): (цвет спереди, метка)} — i по x, j по y (глубина), k по z; и размер кубика."""
    img = _image()
    s = CELL / (FOOT - TOP)
    vox = {}
    for py in range(TOP, FOOT, CELL):
        for px in range(0, img.shape[1] - CELL, CELL):
            cell = img[py:py + CELL, px:px + CELL].reshape(-1, 3)
            solid = cell[(np.abs(cell - 1.0).max(1) > 0.06)]
            if len(solid) < CELL * CELL * 0.5:
                continue
            col = tuple(float(c) for c in np.median(solid, 0))
            label = _label(px + CELL / 2, py + CELL / 2)
            i, k = round((px + CELL / 2 - MID) / CELL), round((FOOT - py - CELL / 2) / CELL)
            y0, y1 = DEPTH["arm" if label.startswith("arm") else label]
            for j in range(round(y0 / s), round(y1 / s) + 1):
                vox[(i, j, k)] = (col if j == round(y0 / s) else None, label)
    # длинные волосы за спиной: от затылка до пояса, шире туловища
    for k in range(round((FOOT - 1000) / CELL), round((FOOT - 560) / CELL)):
        for i in range(round((280 - MID) / CELL), round((650 - MID) / CELL) + 1):
            for j in range(round(0.085 / s) + 1, round(0.125 / s) + 1):
                vox.setdefault((i, j, k), (None, "hair_back"))
    return vox, s


def _side_color(label, front, i, j, k, s, normal):
    """Цвет грани, которой нет на рисунке (бока, спина, верх)."""
    z = k * s - 0.5
    if label in ("head", "hair_side", "hair_back"):
        if label == "head" and normal[2] > 0 and abs(j * s) < 0.03:
            return NAVY                                            # дужка наушников поверх головы
        return _hair(z)
    if label == "cup":                                             # снаружи — тёмная чашка со светящимся кольцом
        if normal[0] != 0:
            d = ((j * s) ** 2 + (z - (0.5 - (447 - TOP) / (FOOT - TOP))) ** 2) ** 0.5
            return CYAN if 0.03 < d < 0.05 else NAVY
        return NAVY
    if label == "torso" or label.startswith("arm"):
        return TRIM if (label == "torso" and z < -0.12) else (front or HOOD)
    return front                                                   # шорты, ноги, обувь — как спереди по высоте


FACES = [((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]), ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
         ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]), ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
         ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]), ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)])]


def make_mesh(bones):
    """Сетка героини из кубиков с цветом на грань и группами вершин по костям (каждый кубик — одной кости)."""
    vox, s = voxels()
    front_of = {}                                                  # цвет спереди для столбца (для боков ног и шорт)
    for (i, j, k), (col, label) in vox.items():
        if col is not None:
            front_of[(i, k)] = col
    verts, faces, cols, groups = [], [], [], []
    for (i, j, k), (col, label) in vox.items():
        front = col or front_of.get((i, k))
        x, z = (i + 0.5) * s, k * s - 0.5
        bone = _bone(label, x, z + s / 2)
        for n, quad in FACES:
            if (i + n[0], j + n[1], k + n[2]) in vox:
                continue
            c = col if (n[1] == -1 and col is not None) else _side_color(label, front, i, j, k, s, n)
            c = c or HOOD
            base = len(verts)
            for qx, qy, qz in quad:
                verts.append(((i + qx - 0.5) * s, (j + qy - 0.5) * s, (k + qz) * s - 0.5))
            faces.append((base, base + 1, base + 2, base + 3))
            cols.append(tuple(v ** 2.2 for v in c))               # sRGB → линейный
            groups.append(bone)
    me = bpy.data.meshes.new("Mia_voxels")
    me.from_pydata(verts, [], faces)
    me.update()
    ca = me.color_attributes.new("col", "FLOAT_COLOR", "CORNER")
    for poly, c in zip(me.polygons, cols):
        for li in poly.loop_indices:
            ca.data[li].color = (*c, 1.0)
    ob = bpy.data.objects.new("Mia_voxels", me)
    bpy.context.scene.collection.objects.link(ob)
    vg = {b: ob.vertex_groups.new(name=b) for b in bones}
    for poly, b in zip(me.polygons, groups):
        vg[b].add(list(poly.vertices), 1.0, "REPLACE")
    mat = bpy.data.materials.new("Mia_voxels")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.6
    attr = mat.node_tree.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "col"
    mat.node_tree.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bev = mat.node_tree.nodes.new("ShaderNodeBevel")              # чуть скруглённые края кубиков
    bev.inputs["Radius"].default_value = s * 0.12
    mat.node_tree.links.new(bev.outputs["Normal"], bsdf.inputs["Normal"])
    me.materials.append(mat)
    return ob
