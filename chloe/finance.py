"""Финансы: подписки и регулярные платежи — сколько, когда спишется, сколько уходит в месяц.

Только записи пользователя: к банкам и картам Chloe не подключается, номеров карт не хранит.
Таблица fin_subs в ~/.chloe/chloe.db (попадает в ежедневные копии). Курсы валют — Центральный банк
Узбекистана (cbu.uz, открытый JSON), раз в сутки. Дата списания, которая прошла, сама переносится на следующий
период: подписка списывается автоматически, отмечать «оплачено» не нужно. Разовый платёж после даты закрывается.
"""
import calendar
import datetime
import sqlite3
import threading
import time

import requests

from .config import JOURNAL_FILE

PERIODS = {"month": "в месяц", "year": "в год", "week": "в неделю", "once": "разово"}
PERIOD_ALIASES = {"месяц": "month", "ежемесячно": "month", "monthly": "month", "год": "year", "ежегодно": "year",
                  "yearly": "year", "annual": "year", "неделя": "week", "еженедельно": "week", "weekly": "week",
                  "разово": "once", "один раз": "once", "однократно": "once"}
CURRENCIES = {"uzs": "UZS", "сум": "UZS", "сумов": "UZS", "сумы": "UZS", "usd": "USD", "$": "USD", "доллар": "USD",
              "долларов": "USD", "eur": "EUR", "€": "EUR", "евро": "EUR", "rub": "RUB", "₽": "RUB", "рубль": "RUB",
              "рублей": "RUB", "cny": "CNY", "юань": "CNY", "юаней": "CNY", "kzt": "KZT", "тенге": "KZT"}
SIGN = {"UZS": "сум", "USD": "$", "EUR": "€", "RUB": "₽", "CNY": "¥", "KZT": "₸"}
RATES_URL = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/"
PER_MONTH = {"month": 1.0, "year": 1 / 12, "week": 52 / 12, "once": 0.0}
_rates = {"at": 0, "data": None}


class FinanceError(Exception):
    pass


def norm_period(p):
    p = (p or "month").lower().strip()
    p = PERIOD_ALIASES.get(p, p)
    if p not in PERIODS:
        raise FinanceError("период: month, year, week или once")
    return p


def norm_currency(c):
    c = (c or "UZS").lower().strip()
    c = CURRENCIES.get(c, c.upper())
    if not (len(c) == 3 and c.isalpha()):
        raise FinanceError("валюта: UZS, USD, EUR, RUB…")
    return c.upper()


def add_period(day, period, n=1):
    if period == "week":
        return day + datetime.timedelta(weeks=n)
    months = n * (12 if period == "year" else 1)
    m = day.month - 1 + months
    y, m = day.year + m // 12, m % 12 + 1
    return day.replace(year=y, month=m, day=min(day.day, calendar.monthrange(y, m)[1]))


def money(amount, cur):
    s = "{:,.2f}".format(amount).rstrip("0").rstrip(".").replace(",", " ")
    return "{} {}".format(s, SIGN.get(cur, cur)) if cur != "USD" else "${}".format(s)


def rates(now=None, get=requests.get):
    """{валюта: сумов за 1 единицу} по курсу ЦБ Узбекистана. Нет связи — прошлые курсы или None."""
    now = now or time.time()
    if _rates["data"] and now - _rates["at"] < 6 * 3600:
        return _rates["data"]
    try:
        r = get(RATES_URL, timeout=10)
        r.raise_for_status()
        data = {"UZS": 1.0}
        for row in r.json():
            data[row["Ccy"]] = float(row["Rate"]) / float(row.get("Nominal") or 1)
        _rates.update(at=now, data=data)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass
    return _rates["data"]


def convert(amount, cur, to, table):
    if cur == to:
        return amount
    if not table or cur not in table or to not in table:
        return None
    return amount * table[cur] / table[to]


class Finance:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS fin_subs (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, amount REAL NOT NULL, currency TEXT NOT NULL,
            period TEXT NOT NULL, next_date TEXT NOT NULL, category TEXT, note TEXT,
            active INTEGER NOT NULL DEFAULT 1, created REAL, last_charged TEXT)""")
        self.db.commit()

    def roll(self, today=None):
        """Прошедшие даты списания → следующий период; разовые после даты закрываются."""
        today = today or datetime.date.today()
        with self.lock:
            for r in self.db.execute("SELECT * FROM fin_subs WHERE active = 1 AND next_date < ?", (today.isoformat(),)).fetchall():
                day = datetime.date.fromisoformat(r["next_date"])
                if r["period"] == "once":
                    self.db.execute("UPDATE fin_subs SET active = 0, last_charged = ? WHERE id = ?", (r["next_date"], r["id"]))
                    continue
                last = day
                while day < today:
                    last, day = day, add_period(day, r["period"])
                self.db.execute("UPDATE fin_subs SET next_date = ?, last_charged = ? WHERE id = ?",
                                (day.isoformat(), last.isoformat(), r["id"]))
            self.db.commit()

    def add(self, name, amount, currency="UZS", period="month", next_date=None, category=None, note=None):
        name = (name or "").strip()
        if not name:
            raise FinanceError("нужно название")
        try:
            amount = float(str(amount).replace(" ", "").replace(",", "."))
        except ValueError:
            raise FinanceError("сумма — число") from None
        if amount <= 0:
            raise FinanceError("сумма больше нуля")
        period = norm_period(period)
        day = datetime.date.fromisoformat(next_date) if next_date else datetime.date.today()
        with self.lock:
            cur = self.db.execute("INSERT INTO fin_subs (name, amount, currency, period, next_date, category, note, created) "
                                  "VALUES (?,?,?,?,?,?,?,?)", (name, amount, norm_currency(currency), period, day.isoformat(),
                                                               category, note, time.time()))
            self.db.commit()
            rid = cur.lastrowid
        self.roll()
        return self.get(rid)

    def get(self, rid):
        with self.lock:
            r = self.db.execute("SELECT * FROM fin_subs WHERE id = ?", (rid,)).fetchone()
        return dict(r) if r else None

    def find(self, text):
        """По номеру или части названия (только активные)."""
        if str(text).strip().isdigit():
            r = self.get(int(text))
            return [r] if r and r["active"] else []
        want = str(text).lower().replace("ё", "е").strip()
        if not want:
            return []
        with self.lock:   # lower() в SQLite не знает кириллицы — сравниваем в Python
            rows = self.db.execute("SELECT * FROM fin_subs WHERE active = 1").fetchall()
        rows = [dict(r) for r in rows]
        exact = [r for r in rows if r["name"].lower().replace("ё", "е") == want]
        return exact or [r for r in rows if want in r["name"].lower().replace("ё", "е")]

    def active(self):
        self.roll()
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM fin_subs WHERE active = 1 ORDER BY next_date, name")]

    def update(self, rid, **fields):
        allowed = {"name", "amount", "currency", "period", "next_date", "category", "note"}
        sets = {k: v for k, v in fields.items() if k in allowed and v not in (None, "")}
        if "period" in sets:
            sets["period"] = norm_period(sets["period"])
        if "currency" in sets:
            sets["currency"] = norm_currency(sets["currency"])
        if "amount" in sets:
            sets["amount"] = float(str(sets["amount"]).replace(" ", "").replace(",", "."))
        if "next_date" in sets:
            sets["next_date"] = datetime.date.fromisoformat(sets["next_date"]).isoformat()
        if not sets:
            return self.get(rid)
        with self.lock:
            self.db.execute("UPDATE fin_subs SET {} WHERE id = ?".format(", ".join(k + " = ?" for k in sets)),
                            list(sets.values()) + [rid])
            self.db.commit()
        self.roll()
        return self.get(rid)

    def stop(self, rid):
        """Отменённая подписка: не удаляется, а уходит в архив (история остаётся)."""
        with self.lock:
            n = self.db.execute("UPDATE fin_subs SET active = 0 WHERE id = ? AND active = 1", (rid,)).rowcount
            self.db.commit()
        return n > 0

    def due(self, days=1, today=None):
        """Списания в ближайшие days дней (0 — только сегодня)."""
        today = today or datetime.date.today()
        self.roll(today)
        end = (today + datetime.timedelta(days=days)).isoformat()
        with self.lock:
            rows = self.db.execute("SELECT * FROM fin_subs WHERE active = 1 AND next_date <= ? ORDER BY next_date",
                                   (end,)).fetchall()
        return [dict(r) for r in rows]

    def monthly(self, to="UZS", table=None):
        """Сколько уходит в месяц в валюте to: (сумма или None, по валютам, без курса)."""
        by_cur, missing = {}, []
        for r in self.active():
            by_cur[r["currency"]] = by_cur.get(r["currency"], 0) + r["amount"] * PER_MONTH[r["period"]]
        total = 0.0
        for cur, amount in by_cur.items():
            v = convert(amount, cur, to, table)
            if v is None:
                missing.append(cur)
            else:
                total += v
        return (None if missing else total), by_cur, missing


DAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def when_text(iso, today=None):
    today = today or datetime.date.today()
    d = datetime.date.fromisoformat(iso)
    delta = (d - today).days
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    if delta == 2:
        return "послезавтра"
    return "{} {:%d.%m}".format(DAYS[d.weekday()], d)


def describe(r, today=None):
    line = "[{}] {} — {} {}".format(r["id"], r["name"], money(r["amount"], r["currency"]), PERIODS[r["period"]])
    if r["active"]:
        line += ", {}: {}".format("списание" if r["period"] != "once" else "оплата", when_text(r["next_date"], today))
    if r.get("category"):
        line += " ({})".format(r["category"])
    return line


def upcoming_text(rows, today=None):
    """«Завтра спишется: Token Plan — $10; …» или пустая строка."""
    if not rows:
        return ""
    parts = ["{} — {} {}".format(r["name"], money(r["amount"], r["currency"]), when_text(r["next_date"], today)) for r in rows]
    return "Скоро списания: " + "; ".join(parts) + "."


finance = Finance(JOURNAL_FILE)
