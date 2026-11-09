"""Навыки в формате Claude (Agent Skills): папка с SKILL.md — описание «когда пользоваться» и инструкция.

Где лежат: ~/.chloe/skills/<имя>/SKILL.md (свои и скачанные) и skills/ в папке проекта (встроенные).
Работает с любой моделью, не только с Claude: в подсказку попадают только имена и короткие описания;
полную инструкцию Chloe читает инструментом use_skill, когда просьба подходит, и делает по ней всё своими
инструментами. Скрипты навыка запускаются через run_command — то есть только после «да».

Установка: python run.py --add-skill <папка или git-ссылка> (из репозитория берутся все папки с SKILL.md).
"""
import pathlib
import re
import shutil
import subprocess
import tempfile

from .config import DATA

USER_DIR = DATA / "skills"
BUILTIN_DIR = pathlib.Path(__file__).resolve().parent.parent / "skills"
MAX_DESC = 300
_cache = {}


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def simple_yaml(text):
    """Шапка SKILL.md без PyYAML: «ключ: значение», многострочные «>» и «|», списки «- …» и «[a, b]».
    Этого хватает для навыков Claude; PyYAML, если установлен, разбирает то же самое."""
    meta, lines, i = {}, text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#") or line[:1] in " \t" or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        block = []
        while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t"):
            block.append(lines[i])
            i += 1
        if val[:1] in (">", "|"):   # многострочный текст: «>» склеивает строки, «|» сохраняет переносы
            rows = [b.strip() for b in block]
            meta[key] = (" ".join(r for r in rows if r) if val[0] == ">" else "\n".join(rows)).strip()
        elif val.startswith("[") and val.endswith("]"):
            meta[key] = [_scalar(x) for x in re.findall(r'"[^"]*"|\'[^\']*\'|[^,\[\]]+', val[1:-1]) if x.strip()]
        elif not val and any(b.strip().startswith("- ") for b in block):
            meta[key] = [_scalar(b.strip()[2:]) for b in block if b.strip().startswith("- ")]
        elif not val and block:
            meta[key] = " ".join(b.strip() for b in block if b.strip())
        else:
            meta[key] = _scalar(val)
    return meta


def front(text):
    """(шапка как словарь, текст после шапки)."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", text, re.S)
    if not m:
        return {}, text
    try:
        import yaml

        meta = yaml.safe_load(m.group(1)) or {}
    except ImportError:
        meta = simple_yaml(m.group(1))
    except Exception:   # кривой YAML в чужом навыке — берём, что разберётся
        meta = simple_yaml(m.group(1))
    return (meta if isinstance(meta, dict) else {}), m.group(2)


def parse(path):
    """SKILL.md → {name, description, body, triggers}. Шапка — YAML между строками ---."""
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = front(text)
    name = str(meta.get("name") or path.parent.name).strip()
    desc = re.sub(r"\s+", " ", str(meta.get("description") or "")).strip()
    t = meta.get("triggers") or []
    triggers = [str(x) for x in (t if isinstance(t, list) else [t]) if str(x).strip()]
    return {"name": name, "description": desc, "body": body.strip(), "dir": path.parent, "triggers": triggers}


def all_skills():
    """Все навыки; свои (~/.chloe/skills) важнее встроенных с тем же именем. Перечитываются, только если файл менялся."""
    found = {}
    for root in (BUILTIN_DIR, USER_DIR):
        if not root.is_dir():
            continue
        for md in sorted(root.glob("*/SKILL.md")):
            try:
                key = (str(md), md.stat().st_mtime)
                if key not in _cache:
                    _cache[key] = parse(md)
                s = _cache[key]
                found[s["name"].lower()] = s
            except OSError:
                continue
    return sorted(found.values(), key=lambda s: s["name"].lower())


def get(name):
    low = str(name).strip().lower()
    skills = all_skills()
    return next((s for s in skills if s["name"].lower() == low), None) or \
        next((s for s in skills if s["dir"].name.lower() == low), None)


def prompt():
    """Строки для системной подсказки: только имя и короткое описание."""
    skills = all_skills()[:60]
    if not skills:
        return ""
    lines = ["- {}: {}".format(s["name"], s["description"][:MAX_DESC] or "(без описания)") for s in skills]
    return ("Твои навыки (папки с инструкциями). Если просьба подходит под навык — сначала прочитай его инструментом "
            "use_skill и делай по инструкции своими инструментами:\n" + "\n".join(lines) + "\n")


def files_of(skill, limit=40):
    out = []
    for p in sorted(skill["dir"].rglob("*")):
        rel = p.relative_to(skill["dir"])
        if p.is_file() and p.name != "SKILL.md" and not any(x.startswith(".") for x in rel.parts):   # без скрытых (.git)
            out.append(str(rel))
        if len(out) >= limit:
            break
    return out


def inside(skill, rel):
    """Файл внутри папки навыка (без выхода наружу через ../)."""
    p = (skill["dir"] / rel).resolve()
    root = skill["dir"].resolve()
    if not (p == root or root in p.parents):
        return None
    if not p.exists():   # инструкции навыков часто пишут FORMS.md, а файл называется forms.md
        low = str(pathlib.Path(rel)).lower()
        p = next((root / f for f in files_of(skill, limit=500) if f.lower() == low), p)
    return p


# ---------- установка ----------

def find_skill_dirs(root):
    return sorted({md.parent for md in pathlib.Path(root).rglob("SKILL.md") if ".git" not in md.parts})


def add(source):
    """Копирует навыки из папки или git-репозитория в ~/.chloe/skills. Возвращает имена."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        src = pathlib.Path(source).expanduser()
        if not src.exists():
            if not re.match(r"^(https://|git@)", source):
                raise ValueError("Нет такой папки и это не git-ссылка: " + source)
            tmp = tempfile.mkdtemp(prefix="chloe-skill-")
            subprocess.run(["git", "clone", "--depth", "1", source, tmp], check=True, capture_output=True, timeout=180)
            src = pathlib.Path(tmp)
        dirs = find_skill_dirs(src)
        if not dirs:
            raise ValueError("В «{}» нет ни одного SKILL.md".format(source))
        added = []
        for d in dirs:
            s = parse(d / "SKILL.md")
            target = USER_DIR / re.sub(r"[^\w.-]+", "-", s["name"]).strip("-")
            if target.exists():
                shutil.rmtree(target)   # обновление навыка с тем же именем
            shutil.copytree(d, target, ignore=shutil.ignore_patterns(".git"))
            added.append(s["name"])
        return added
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
