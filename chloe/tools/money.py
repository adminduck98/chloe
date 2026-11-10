"""Инструмент subscriptions — подписки и регулярные платежи пользователя."""
from .. import finance as fin
from ..finance import FinanceError, finance
from ..voice import confirm

NOTE = ("Это записи пользователя, к банку я не подключена. Номера карт и пароли не записываю, даже если их назовут.")


def _total_text(to="UZS"):
    table = fin.rates()
    total, by_cur, missing = finance.monthly(to, table)
    if not by_cur:
        return "Подписок пока нет."
    parts = ", ".join(fin.money(v, c) for c, v in sorted(by_cur.items()))
    if total is None:
        return "В месяц уходит: {} (курса для {} нет — общую сумму не посчитать).".format(parts, ", ".join(missing))
    usd = fin.convert(total, to, "USD", table) if to != "USD" else None
    line = "В месяц уходит примерно {}".format(fin.money(round(total), to))
    if usd:
        line += " (≈ {})".format(fin.money(round(usd, 2), "USD"))
    if len(by_cur) > 1:
        line += "; по валютам: " + parts
    rate = table.get("USD") if table else None
    return line + "." + (" Курс ЦБ Узбекистана: $1 = {} сум.".format(fin.money(rate, "UZS").replace(" сум", "")) if rate else "")


def tool_subscriptions(a):
    action = a.get("action", "list")
    try:
        if action == "list":
            rows = finance.active()
            if not rows:
                return "Подписок и регулярных платежей пока нет. " + NOTE
            return "\n".join(fin.describe(r) for r in rows) + "\n" + _total_text()
        if action == "total":
            return _total_text(fin.norm_currency(a.get("currency") or "UZS"))
        if action == "due":
            rows = finance.due(max(0, min(int(a.get("days") or 7), 62)))
            return "\n".join(fin.describe(r) for r in rows) if rows else "В ближайшие дни списаний нет."
        if action == "add":
            r = finance.add(a.get("name"), a.get("amount"), a.get("currency"), a.get("period"), a.get("next_date"),
                            a.get("category"), a.get("note"))
            return "Записала: " + fin.describe(r) + ". За день до списания напомню (в утренней сводке и при запуске)."
        if action in ("edit", "stop"):
            found = finance.find(a.get("id") or a.get("name") or "")
            if not found:
                return "Такой подписки не нашла."
            if len(found) > 1:
                return "Нашла несколько — какую? Назови id:\n" + "\n".join(fin.describe(r) for r in found)
            r = found[0]
            if action == "stop":
                if not confirm("Убрать «{}» из подписок? (В архив, историю не стираю.)".format(r["name"])):
                    return "Оставила."
                finance.stop(r["id"])
                return "Убрала «{}» из подписок. Отменить саму подписку нужно на сайте сервиса — я этого не делаю.".format(r["name"])
            r = finance.update(r["id"], name=a.get("new_name"), amount=a.get("amount"), currency=a.get("currency"),
                               period=a.get("period"), next_date=a.get("next_date"), category=a.get("category"), note=a.get("note"))
            return "Исправила: " + fin.describe(r)
    except FinanceError as e:
        return "Не могу: {}.".format(e)
    except ValueError:
        return "Не поняла число или дату (дата — 2026-11-25)."
    return "Неизвестное действие: " + action
