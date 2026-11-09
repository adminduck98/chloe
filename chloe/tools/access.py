"""Карта прав голосом: «что тебе разрешено?», «запрети читать Telegram», «сделай папку Личное приватной»."""
from ..permissions import CATEGORIES, LEVEL_RU, LEVELS, permissions, usage
from ..voice import confirm
from .paths import P, short

FIND = {k: [k, t.lower()] + [w for w in d.lower().replace(",", " ").split() if len(w) > 3] for k, (t, d, _, _) in CATEGORIES.items()}


def find_category(name):
    n = (name or "").lower().strip()
    if n in CATEGORIES:
        return n
    hits = [k for k, words in FIND.items() if any(n in w or w in n for w in words if w)]
    return hits[0] if len(hits) == 1 else None


def tool_permissions(a):
    action = a.get("action", "show")
    if action == "show":
        use = usage(7)
        lines = []
        for c in permissions.map(use)["categories"]:
            lines.append("{} — {}{}".format(c["title"], c["level_ru"], " (за неделю: {})".format(c["uses"]) if c["uses"] else ""))
        vault = permissions.vault
        lines.append("Private Vault (приватные папки): " + (", ".join(short(P(v)) for v in vault) if vault else "пусто"))
        return "\n".join(lines)
    if action == "set":
        key = find_category(a.get("category", ""))
        level = a.get("level")
        if not key:
            return "Не поняла, какая категория. Есть: " + ", ".join(t for t, _, _, _ in CATEGORIES.values()) + "."
        if level not in LEVELS:
            return "Уровень: allow (разрешено), ask (спрашивать) или block (запрещено)."
        title = CATEGORIES[key][0]
        if permissions.level(key) == level:
            return "«{}» уже {}.".format(title, LEVEL_RU[level])
        if permissions.loosens(key, level) and not confirm("Ослабить защиту: «{}» — {}?".format(title, LEVEL_RU[level])):
            return "Пользователь не подтвердил — права не изменены."
        permissions.set_level(key, level)
        return "Готово: «{}» — {}.".format(title, LEVEL_RU[level])
    if action == "vault_add":
        p = P(a.get("path", ""))
        if not a.get("path"):
            return "Какую папку сделать приватной? Нужен путь."
        added = permissions.vault_add(p)
        return "Папка {} теперь в Private Vault: внутрь не заглядываю, изученные оттуда документы в ответах не участвуют.".format(short(P(added)))
    if action == "vault_remove":
        p = P(a.get("path", ""))
        if not permissions.in_vault(p) or str(permissions._norm(p)) not in permissions.vault:
            return "Такой папки нет в Private Vault. Там: " + (", ".join(permissions.vault) or "пусто") + "."
        if not confirm("Убрать папку {} из Private Vault? Тогда я смогу её читать.".format(short(p))):
            return "Пользователь не подтвердил — папка остаётся приватной."
        permissions.vault_remove(p)
        return "Папка {} больше не приватная.".format(short(p))
    return "Действие: show, set, vault_add или vault_remove."
