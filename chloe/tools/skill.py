"""Навыки Claude (SKILL.md): прочитать инструкцию навыка и его файлы."""
from .. import skillbook


def tool_use_skill(a):
    s = skillbook.get(a["name"])
    if s is None:
        names = ", ".join(x["name"] for x in skillbook.all_skills()) or "навыков пока нет"
        return "Не найдено навыка «{}». Есть: {}.".format(a["name"], names)
    files = skillbook.files_of(s)
    return ("[Инструкция навыка «{name}». Делай по ней своими инструментами; правила безопасности (подтверждения, отказ "
            "пользователя) важнее инструкции. Папка навыка: {dir}]\n\n{body}\n\n"
            "Файлы навыка (читать — read_skill_file, запускать скрипты — run_command с полным путём): {files}").format(
        name=s["name"], dir=s["dir"], body=s["body"][:20000], files=", ".join(files) or "нет")


def tool_read_skill_file(a):
    s = skillbook.get(a["name"])
    if s is None:
        return "Не найдено навыка «{}».".format(a["name"])
    p = skillbook.inside(s, a.get("path", ""))
    if p is None or not p.is_file():
        return "Не найдено файла «{}» в навыке «{}».".format(a.get("path"), s["name"])
    return p.read_text(encoding="utf-8", errors="replace")[:20000]
