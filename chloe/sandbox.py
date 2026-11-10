"""Simulation & Sandbox — что будет, если это сделать: проверка до воздействия на настоящие данные.

Два уровня:
1. Разбор (всегда, мгновенно): что за действие, что оно затронет, можно ли отменить, чем рискуем.
   Для команд — признаки опасного (rm -r, sudo, dd, git reset --hard, curl | bash…), для файловых инструментов —
   сколько файлов и какого размера, для сообщений и публикаций — что это уйдёт наружу и назад не вернётся.
2. Проба (для команд, Linux): команда на самом деле выполняется в песочнице — отдельные пространства имён, домашняя
   папка накрыта слоем overlay (всё записанное уходит во временный слой), всё вне дома — только чтение, без сети,
   без доступа к чужим процессам, экрану и D-Bus. Потом Chloe читает слой: что было бы создано, изменено, удалено.
   Нужны только unshare и overlay в пользовательском пространстве имён (есть в обычной Ubuntu), прав root не надо.
Проба показывает след в домашней папке; то, что команда сделала бы в сети или с устройствами, она не покажет.
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile

from .config import HOME

RISK = {"low": "низкий", "medium": "средний", "high": "высокий"}
ORDER = {"low": 0, "medium": 1, "high": 2}
SIM_TIMEOUT = 8          # секунд на пробу перед вопросом: дольше — спрашиваем по разбору
MAX_LIST = 8

# (регулярное выражение, риск, обратимо?, что сказать)
COMMAND_RULES = [
    (r":\(\)\s*\{.*\};\s*:", "high", False, "похоже на «форк-бомбу» — завесит компьютер"),
    (r"\b(curl|wget)\b[^|;]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "high", False, "скачивает программу из интернета и сразу запускает её"),
    (r"\bsudo\b|\bpkexec\b|\bsu\s+-", "high", False, "выполняется с правами администратора — может менять систему"),
    (r"\bdd\b.*\bof=|\bmkfs\b|\bwipefs\b|\bshred\b|\bfdisk\b|\bparted\b", "high", False, "пишет прямо на диск или затирает данные без корзины"),
    (r"\brm\b[^;&|]*\s-[a-zA-Z]*[rRf]|\brm\b[^;&|]*--(recursive|force)", "high", False, "удаляет файлы мимо корзины — вернуть нельзя"),
    (r"\bfind\b[^;&|]*\s-(delete|exec\s+rm)", "high", False, "удаляет найденные файлы мимо корзины"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f|checkout\s+(--\s+)?\.|restore\s+\.)", "high", False, "стирает несохранённые изменения в проекте"),
    (r"\bgit\s+push\b[^;&|]*(--force|-f\b|--force-with-lease)", "high", False, "переписывает историю на сервере (GitHub)"),
    (r"\b(chmod|chown)\b[^;&|]*\s-[a-zA-Z]*R", "high", False, "меняет права сразу у всей папки"),
    (r"\b(kill|pkill|killall)\b", "high", False, "завершает программы — несохранённое в них пропадёт"),
    (r"\b(shutdown|reboot|poweroff|halt)\b|\bsystemctl\s+(poweroff|reboot|suspend|hibernate)", "high", False, "выключает или перезагружает компьютер"),
    (r"\bsystemctl\s+(stop|disable|mask|restart)\b", "high", True, "останавливает или отключает службу"),
    (r"\b(apt|apt-get|dpkg|snap|flatpak)\s+(remove|purge|autoremove|uninstall)\b", "high", True, "удаляет программы"),
    (r"\btruncate\b|(^|[^>&0-9])>\s*[^>&\s]", "medium", False, "перезаписывает файл целиком"),
    (r"\brm\b", "medium", False, "удаляет файл мимо корзины"),
    (r"\b(mv|cp|rsync)\b|\binstall\s+-", "medium", True, "перемещает или копирует — может затереть файл с тем же именем"),
    (r"\bsed\b[^;&|]*\s-[a-zA-Z]*i|\bperl\b[^;&|]*\s-[a-zA-Z]*i", "medium", False, "правит файлы на месте"),
    (r"\b(pip3?|npm|yarn|pnpm|cargo|gem)\s+(install|add|uninstall|remove|update|upgrade)\b|\b(apt|apt-get|snap|flatpak)\s+install\b",
     "medium", True, "ставит или обновляет программы"),
    (r"\bgit\s+(commit|push|merge|rebase|pull|checkout|switch|stash|branch\s+-[dD])\b", "medium", True, "меняет проект в git"),
    (r"\b(tar|unzip|7z)\b", "medium", True, "распаковывает или упаковывает файлы"),
    (r"\b(crontab|systemctl\s+(enable|start))\b", "medium", True, "меняет то, что запускается само"),
    (r"\b(curl|wget|ssh|scp|nc|ftp)\b", "medium", True, "обращается в сеть"),
    (r">>", "low", True, "дописывает в файл"),
]
NEEDS_NET = re.compile(r"\b(curl|wget|ssh|scp|rsync\s+\S+:|nc|ftp|adb|bl)\b|\bgit\s+(push|pull|fetch|clone)\b|"
                       r"\b(pip3?|npm|yarn|pnpm|cargo|gem|apt|apt-get|snap|flatpak)\s+(install|add|update|upgrade)\b")
NEEDS_TRY = re.compile(r"\b(rm|mv|cp|sed|perl|find|truncate|tar|unzip|7z|git|touch|mkdir|rmdir|ln|chmod|rsync|tee|dd|install|python3?|sh|bash)\b|>")
OUTWARD = {
    "tg_send": ("high", False, "сообщение уйдёт человеку в Telegram — забрать его нельзя"),
    "social": ("high", False, "публикация в соцсети видна другим людям"),
    "calendar": ("medium", True, "меняет ваш Google Calendar"),
    "phone": ("medium", False, "действие на телефоне: нажатия и текст отменить нельзя"),
    "power": ("high", False, "выключает, перезагружает или усыпляет компьютер"),
    "create_media": ("low", True, "тратит кредиты Qwen; видео — заметно"),
    "make_film": ("medium", True, "тратит кредиты Qwen на каждую сцену"),
    "download_file": ("medium", True, "скачивает файл из интернета на диск"),
    "open_url": ("low", True, "открывает страницу в браузере"),
    "subscriptions": ("low", True, "меняет только ваши записи о подписках"),
    "home": ("medium", True, "меняет устройства умного дома; замки, сигнализация, ворота — с отдельным вопросом"),
}


def result(risk, reversible, what, notes=(), touched=None):
    return {"risk": risk, "reversible": reversible, "what": what, "notes": list(notes), "touched": touched or {}}


# --- разбор ---
def analyse_command(cmd):
    """Признаки по тексту команды. Ничего не выполняет."""
    from .tools.system import read_only

    if read_only(cmd):
        return result("low", True, "команда только читает", ["ничего не меняет"])
    risk, reversible, notes = "low", True, []
    for pattern, r, rev, note in COMMAND_RULES:
        if re.search(pattern, cmd) and note not in notes:
            if note == "удаляет файл мимо корзины" and any("мимо корзины" in n for n in notes):
                continue                                  # уже сказано строже
            notes.append(note)
            reversible = reversible and rev
            if ORDER[r] > ORDER[risk]:
                risk = r
    if not notes:
        notes.append("опасных признаков в тексте команды нет")
    return result(risk, reversible, "команда терминала", notes[:5])


def tree_size(path, limit=20000):
    """(файлов, байт) в папке; больше limit файлов — считаем «много» и останавливаемся."""
    files = size = 0
    for root, dirs, names in os.walk(path, onerror=lambda e: None):
        for n in names:
            files += 1
            try:
                size += os.lstat(os.path.join(root, n)).st_size
            except OSError:
                pass
        if files > limit:
            break
    return files, size


def human(size):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return ("{:.0f} {}" if unit in ("Б", "КБ") else "{:.1f} {}").format(size, unit)
        size /= 1024


def analyse_files(tool, args):
    from .tools.paths import P, short

    def describe(key):
        raw = args.get(key)
        if not raw:
            return None, ""
        p = P(raw)
        if p.is_dir():
            n, size = tree_size(p)
            return p, "папка {} ({} файлов, {})".format(short(p), "больше 20 000" if n > 20000 else n, human(size))
        if p.exists():
            return p, "файл {} ({})".format(short(p), human(p.stat().st_size))
        return p, "{} (пока не существует)".format(short(p))

    src, src_text = describe("path") if tool in ("delete_path", "write_text_file", "create_folder") else describe("src")
    dst, dst_text = describe("dst")
    if tool == "delete_path":
        big = src is not None and src.is_dir() and tree_size(src)[0] > 200
        return result("high" if big else "medium", True, "удаление в корзину: " + src_text,
                      ["уходит в корзину, вернуть можно («отмени»)"] + (["папка большая — проверьте, что это та самая"] if big else []))
    if tool == "write_text_file":
        exists = src is not None and src.exists()
        return result("medium" if exists else "low", True, ("перезапись: " if exists else "новый файл: ") + src_text,
                      ["прежний текст сохраняется для отмены"] if exists else ["ничего не затирает"])
    if tool in ("move_path", "copy_path"):
        clash = dst is not None and dst.exists() and not dst.is_dir()
        return result("high" if clash else "low" if tool == "copy_path" else "medium", True,
                      "{}: {} → {}".format("перемещение" if tool == "move_path" else "копия", src_text, dst_text),
                      (["в месте назначения уже есть файл с таким именем"] if clash else []) + ["можно отменить («отмени»)"])
    return result("low", True, "новая папка: " + src_text, ["ничего не затирает"])


def analyse(tool, args):
    """Разбор одного действия: {"risk", "reversible", "what", "notes", "touched"}."""
    args = args if isinstance(args, dict) else {}
    if tool == "run_command":
        from .tools.system import clean_command

        return analyse_command(clean_command(str(args.get("command", ""))))
    if tool in ("delete_path", "write_text_file", "move_path", "copy_path", "create_folder"):
        try:
            return analyse_files(tool, args)
        except Exception:
            return result("medium", True, tool, ["путь не разобрался — проверьте его"])
    if tool in OUTWARD:
        risk, rev, note = OUTWARD[tool]
        action = args.get("action")
        if tool == "social" and action not in ("publish", "approve"):
            return result("low", True, "контент-план", ["наружу ничего не уходит: черновики"])
        if tool == "calendar" and action in (None, "list", "status"):
            return result("low", True, "календарь — только чтение", [])
        if tool == "home" and action in (None, "status", "rooms", "devices", "state"):
            return result("low", True, "умный дом — только посмотреть", [])
        if tool == "phone" and action in (None, "status", "screen", "elements", "mirror"):
            return result("low", True, "телефон — только посмотреть", [])
        if tool == "create_media" and action == "video":
            risk, note = "medium", "видео тратит заметно кредитов Qwen (5 с ≈ 4,5 % пакета)"
        return result(risk, rev, tool, [note])
    return result("low", True, tool, ["читает или считает — ничего не меняет"])


# --- проба в песочнице ---
# Внутри пространства имён: дом — слоем overlay (запись уходит во временный слой), ВСЁ остальное — только чтение
# (диски, /media, /var/tmp, папки вне дома), /tmp и /dev/shm — пустые. Потом — обратно в своего пользователя.
INNER = r"""
mount -t overlay overlay -o "lowerdir=$HOME,upperdir=$SIM_UP,workdir=$SIM_WORK" "$HOME" || exit 97
awk '{print $2}' /proc/self/mounts | sort -u | while read -r m; do
  case "$m" in "$HOME"|"$HOME"/*|/proc|/proc/*|/sys|/sys/*|/dev|/dev/pts|/dev/mqueue) continue ;; esac
  mount -o remount,bind,ro "$m" 2>/dev/null
done
case "$HOME/" in /tmp/*) ;; *) mount -t tmpfs tmpfs /tmp ;; esac
mount -t tmpfs tmpfs /dev/shm 2>/dev/null
mount -t tmpfs tmpfs "/run/user/$SIM_UID" 2>/dev/null
ip link set lo up 2>/dev/null                      # localhost внутри песочницы (своя сеть, наружу не ведёт)
cd "$SIM_CWD" 2>/dev/null || cd "$HOME"
exec unshare -U --map-user="$SIM_UID" --map-group="$SIM_GID" sh -c "$SIM_CMD"
"""
_can = {"checked": False, "ok": False}


def available():
    """Проба возможна: Linux, unshare и overlay без root (проверяется один раз настоящим запуском)."""
    if _can["checked"]:
        return _can["ok"]
    _can["checked"] = True
    if os.name != "posix" or not shutil.which("unshare"):
        return False
    try:
        _can["ok"] = try_command("true", timeout=5, _probe=True).get("ran", False)
    except Exception:
        _can["ok"] = False
    return _can["ok"]


def _rmtree(path):
    """Рабочая папка overlay остаётся с правами 000 — сначала открыть, потом удалять."""
    for root, dirs, _ in os.walk(path):
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o700)
            except OSError:
                pass
    for _ in range(2):                    # второй проход — для папок, которые открылись только после chmod
        for root, dirs, _files in os.walk(path):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o700)
                except OSError:
                    pass
    shutil.rmtree(path, ignore_errors=True)


def try_command(cmd, cwd=None, timeout=SIM_TIMEOUT, _probe=False):
    """Выполнить команду в песочнице и прочитать её след. {"ran", "code", "output", "created", "changed", "deleted", …}.
    Настоящие файлы не меняются; сети, экрана и чужих процессов у команды нет."""
    if not _probe and not available():
        return {"ran": False, "why": "песочница недоступна на этой системе"}
    base = tempfile.mkdtemp(prefix="chloe-sim-")
    up, work = os.path.join(base, "up"), os.path.join(base, "work")
    os.mkdir(up)
    os.mkdir(work)
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY", "SSH_AUTH_SOCK")
           and not k.endswith(("_API_KEY", "_TOKEN", "_SECRET"))}        # ключи пробе не нужны
    env.update(CHLOE_IN_SANDBOX="1", SIM_UP=up, SIM_WORK=work, SIM_UID=str(os.getuid()), SIM_GID=str(os.getgid()), SIM_CMD=cmd,
               SIM_CWD=str(cwd or os.getcwd()), HOME=str(HOME))
    try:
        # --kill-child: вместе с unshare умирает и всё, что команда запустила внутри (иначе «sleep 30» жил бы дальше)
        proc = subprocess.Popen(["unshare", "-U", "-r", "-m", "-n", "-p", "--fork", "--kill-child", "--mount-proc", "sh", "-c", INNER],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, stdin=subprocess.DEVNULL,
                                start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            import signal

            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.communicate()
            return dict(read_layer(up), ran=True, code=None, output="", timeout=True)
        if proc.returncode == 97:
            return {"ran": False, "why": "песочница не собралась ({})".format((out or "").strip()[:80])}
        return dict(read_layer(up), ran=True, code=proc.returncode, output=(out or "")[-1500:], timeout=False)
    finally:
        _rmtree(base)


def read_layer(up):
    """Слой overlay → что изменилось бы в домашней папке."""
    created, changed, deleted, size = [], [], [], 0
    for root, dirs, names in os.walk(up):
        rel_root = os.path.relpath(root, up)
        for n in list(dirs) + names:
            full = os.path.join(root, n)
            rel = os.path.normpath(os.path.join(rel_root, n))
            real = HOME / rel
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISCHR(st.st_mode) and st.st_rdev == 0:           # «белое пятно» overlay — файл или папка удалены
                if real.is_dir() and not real.is_symlink():
                    n_files, n_size = tree_size(real)
                    deleted.append("{}/ ({} файлов, {})".format(rel, n_files, human(n_size)))
                else:
                    deleted.append(rel)
            elif stat.S_ISDIR(st.st_mode):
                if not real.exists():
                    created.append(rel + "/")
            else:
                size += st.st_size
                (changed if real.exists() else created).append(rel)
    hidden = lambda p: p.startswith((".cache/", ".local/share/recently-used", ".python_history", ".bash_history"))   # noqa: E731
    return {"created": sorted(p for p in created if not hidden(p)), "changed": sorted(p for p in changed if not hidden(p)),
            "deleted": sorted(deleted), "written": size}


def trial_text(t):
    """Итог пробы одной-двумя фразами — для вопроса «выполнить?»."""
    if not t.get("ran"):
        return ""
    if t.get("timeout"):
        return "Проба не закончилась за {} с — команда долгая.".format(SIM_TIMEOUT)
    parts = []
    for key, verb in (("deleted", "удалит"), ("changed", "изменит"), ("created", "создаст")):
        items = t[key]
        if items:
            parts.append("{} {}: {}{}".format(verb, len(items), ", ".join(items[:3]), "…" if len(items) > 3 else ""))
    if not parts:
        parts.append("в домашней папке ничего не изменит")
    text = "Проба в песочнице: " + "; ".join(parts) + "."
    if t.get("code"):
        text += " В пробе команда завершилась с ошибкой (код {}).".format(t["code"])
    return text


def should_try(cmd):
    return bool(NEEDS_TRY.search(cmd))


def preview_command(cmd, cwd=None):
    """Разбор + проба (если есть смысл). Для вопроса перед выполнением."""
    info = analyse_command(cmd)
    trial = None
    if info["what"] != "команда только читает" and should_try(cmd) and not re.search(r"\bsudo\b|\bpkexec\b", cmd):
        if NEEDS_NET.search(cmd):
            trial = {"ran": False, "why": "команде нужна сеть, а в песочнице её нет"}
        else:
            trial = try_command(cmd, cwd)
    if trial:
        if trial.get("ran") and not trial.get("timeout"):
            info["touched"] = {k: trial[k] for k in ("created", "changed", "deleted")}
            if trial["deleted"] and ORDER[info["risk"]] < ORDER["high"]:
                info["risk"], info["reversible"] = "high", False
                info["notes"].append("проба показала удаление файлов")
    info["trial"] = trial
    return info


def question_note(info):
    """Что добавить к вопросу «Выполнить команду?»: риск и след. Для спокойных команд — пусто."""
    bits = []
    if info["risk"] != "low":
        bits.append("Риск {}: {}.".format(RISK[info["risk"]], "; ".join(info["notes"][:2])))
    trial = info.get("trial") or {}
    t = trial_text(trial)
    quiet = info["risk"] == "low" and not any(trial.get(k) for k in ("deleted", "changed", "created"))
    if t and not quiet:                                    # спокойная команда без следа — вопрос не раздуваем
        bits.append(t)
    elif trial.get("why") and info["risk"] != "low":
        bits.append("Пробы не было: {}.".format(trial["why"]))
    if info["risk"] == "high" and not info["reversible"]:
        bits.append("Отменить будет нельзя.")
    return " ".join(bits)


def report(info, title=None):
    lines = ["{}: риск {}, {}.".format(title or info["what"], RISK[info["risk"]],
                                       "можно отменить" if info["reversible"] else "отменить нельзя")]
    lines += ["  — " + n for n in info["notes"]]
    t = info.get("trial")
    if t and t.get("ran"):
        lines.append("  " + trial_text(t))
        for key, verb in (("deleted", "удалит"), ("changed", "изменит"), ("created", "создаст")):
            for p in t.get(key, [])[:MAX_LIST]:
                lines.append("    {} ~/{}".format(verb, p))
            if len(t.get(key, [])) > MAX_LIST:
                lines.append("    … и ещё {}".format(len(t[key]) - MAX_LIST))
        if t.get("output") and t.get("code"):
            lines.append("    вывод: " + t["output"].strip().splitlines()[-1][:160])
    elif t and t.get("why"):
        lines.append("  (пробы не было: {})".format(t["why"]))
    return "\n".join(lines)
