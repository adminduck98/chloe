"""Движения 3D-героини (сами позы — в chloe/blender/hero3d.py, внутри Blender). Здесь — список и длительности,
чтобы Chloe знала длину ролика без Blender."""
MOVES = ("idle", "wave", "jump", "walk", "dance", "turn")
SECONDS = {"idle": 1.5, "wave": 2.0, "jump": 1.6, "walk": 2.0, "dance": 2.4, "turn": 2.0}   # как в hero3d.py


def plan(moves):
    out, t = [], 0.0
    for m in [m for m in (moves or []) if m in SECONDS] or ["idle", "wave", "jump"]:
        out.append((m, t, t + SECONDS[m]))
        t += SECONDS[m]
    return out, t
