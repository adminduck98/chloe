"""Peach & Puff World — постоянный мир сериала (библия мира владельца, 16.11.2026).

Канон (не меняется сам): chloe/assets/peach-puff-world/ — библия мира, герои, локации с описаниями для Qwen.
Живая память (меняется от серии к серии): ~/.chloe/peach-puff-world/ — утверждённые картинки-образцы локаций,
история серий и состояние мира (предметы, которые переставили или испачкали, — до уборки).
«Every episode must feel like another day in the same world. Only the adventures change.»
"""
import json
import pathlib
import time

from .config import DATA

CANON = pathlib.Path(__file__).resolve().parent / "assets" / "peach-puff-world"
LIVE = DATA / "peach-puff-world"
REFS = LIVE / "references" / "locations"
HISTORY = LIVE / "memory" / "episode_history.json"
STATE = LIVE / "memory" / "world_state.json"
DEFAULT = "living_room"            # главная сцена сериала

MASTER = ("A cozy hand-drawn children's cartoon world illustrated on warm textured paper. Traditional colored pencil and "
          "marker artwork, imperfect uneven black outlines, soft pastel colors, visible pencil strokes, slightly imperfect "
          "coloring outside the lines. The world feels like a charming illustrated storybook. All architecture, furniture "
          "and objects must have consistent shapes, proportions, colors and positions across every scene. Flat 2D "
          "illustration only. No 3D, no CGI, no photorealism, no gradients, no glossy surfaces, no digital painting appearance.")


def locations():
    """{id: {name, about, keywords, prompt, fixed}} — все утверждённые места мира."""
    out = {}
    for f in sorted((CANON / "locations").rglob("*.json")):
        try:
            loc = json.loads(f.read_text(encoding="utf-8"))
            out[loc["id"]] = loc
        except (OSError, ValueError, KeyError):
            pass
    return out


def location(loc_id):
    locs = locations()
    return locs.get(loc_id) or locs.get(DEFAULT)


def guess(text):
    """Локация по словам («торт на кухне» → kitchen); не нашлось — гостиная."""
    low = (text or "").lower()
    best, score = DEFAULT, 0
    for loc_id, loc in locations().items():
        s = sum(1 for w in loc.get("keywords", []) if w.lower() in low)
        if s > score:
            best, score = loc_id, s
    return best


def reference(loc_id):
    """Утверждённая картинка-образец локации или None."""
    p = REFS / "{}.png".format(loc_id)
    return p if p.exists() else None


def menu():
    """Список мест для сценариста: «id — название (детали)»."""
    return "\n".join("{} — {}{}".format(i, l["name"], (": " + "; ".join(l["fixed"])) if l.get("fixed") else "")
                     for i, l in locations().items())


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def history():
    return _load(HISTORY, [])


def state():
    """{"props": {"гостиная: пятно от чая на ковре": "серия 7"}, ...} — что изменилось в мире и не убрано."""
    return _load(STATE, {"props": {}})


def continuity():
    """Что сценаристу надо помнить о мире: последние серии и неубранные изменения."""
    h = history()[-5:]
    lines = ["Прошлые серии: " + "; ".join("№{} «{}» ({})".format(e["n"], e["title"], location(e.get("location"))["name"])
                                         for e in h) if h else "Это первая серия в памяти мира."]
    props = state().get("props", {})
    if props:
        lines.append("Изменения в мире, которые ещё не убраны: " + "; ".join(props))
    return "\n".join(lines)


def record(plan, video=None, now=None):
    """Серия готова: в историю мира (номер, название, место, реплики, файл) и изменения предметов из плана."""
    h = history()
    n = (h[-1]["n"] + 1) if h else 1
    h.append({"n": n, "title": plan.get("title", ""), "location": plan.get("location", DEFAULT),
              "date": time.strftime("%Y-%m-%d", time.localtime(now or time.time())),
              "words": [b.get("words", "") for b in plan.get("beats", [])], "video": str(video) if video else None})
    _save(HISTORY, h)
    st = state()
    for change in plan.get("world_changes") or []:
        st.setdefault("props", {})[str(change)[:120]] = "серия {}".format(n)
    for fixed in plan.get("world_fixed") or []:
        st.get("props", {}).pop(str(fixed)[:120], None)
    _save(STATE, st)
    return n
