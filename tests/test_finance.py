"""Финансы: подписки, даты списаний, сумма в месяц, напоминания. Курс ЦБ подменён."""
import datetime
import unittest
from unittest import mock

from chloe import app
from chloe import finance as fin
from chloe.finance import Finance, FinanceError
from chloe.permissions import TOOL_CATEGORY
from chloe.settings import settings
from chloe.tools import HANDLERS
from chloe.tools import money
from chloe.tools import news as tn

D = datetime.date
TABLE = {"UZS": 1.0, "USD": 12000.0, "EUR": 13400.0}


class Dates(unittest.TestCase):
    def test_add_period(self):
        self.assertEqual(fin.add_period(D(2026, 1, 31), "month"), D(2026, 2, 28))
        self.assertEqual(fin.add_period(D(2026, 12, 15), "month"), D(2027, 1, 15))
        self.assertEqual(fin.add_period(D(2028, 2, 29), "year"), D(2029, 2, 28))
        self.assertEqual(fin.add_period(D(2026, 11, 10), "week"), D(2026, 11, 17))

    def test_when_text(self):
        t = D(2026, 11, 10)
        self.assertEqual([fin.when_text(d, t) for d in ("2026-11-10", "2026-11-11", "2026-11-12")], ["сегодня", "завтра", "послезавтра"])
        self.assertEqual(fin.when_text("2026-11-20", t), "пт 20.11")

    def test_money_and_currency(self):
        self.assertEqual(fin.money(150000, "UZS"), "150 000 сум")
        self.assertEqual(fin.money(9.99, "USD"), "$9.99")
        self.assertEqual(fin.norm_currency("долларов"), "USD")
        self.assertEqual(fin.norm_period("ежегодно"), "year")
        with self.assertRaises(FinanceError):
            fin.norm_period("иногда")


class Store(unittest.TestCase):
    def setUp(self):
        self.f = Finance(":memory:")

    def test_roll_forward_and_once(self):
        a = self.f.add("Token Plan", 10, "USD", "month", "2026-09-07")
        b = self.f.add("Ремонт", 500000, "UZS", "once", "2026-11-01")
        self.f.roll(D(2026, 11, 10))
        a, b = self.f.get(a["id"]), self.f.get(b["id"])
        self.assertEqual((a["next_date"], a["last_charged"]), ("2026-12-07", "2026-11-07"))
        self.assertEqual(b["active"], 0)

    def test_due_and_monthly(self):
        today = datetime.date.today()
        self.f.add("Netflix", 9, "USD", "month", (today + datetime.timedelta(days=1)).isoformat())
        self.f.add("Интернет", 150000, "UZS", "month", (today + datetime.timedelta(days=10)).isoformat())
        self.f.add("Домен", 24, "USD", "year", (today + datetime.timedelta(days=100)).isoformat())
        self.assertEqual([r["name"] for r in self.f.due(1)], ["Netflix"])
        total, by_cur, missing = self.f.monthly("UZS", TABLE)
        self.assertAlmostEqual(total, 9 * 12000 + 150000 + 2 * 12000)
        self.assertEqual(missing, [])
        self.assertEqual(self.f.monthly("UZS", None)[0], None)              # нет курса — общую сумму не выдумываем

    def test_find_edit_stop(self):
        r = self.f.add("Spotify", 5, "USD")
        self.assertEqual(self.f.find("spot")[0]["id"], r["id"])
        self.assertEqual(self.f.update(r["id"], amount="6,5")["amount"], 6.5)
        self.assertTrue(self.f.stop(r["id"]))
        self.assertEqual(self.f.find("spot"), [])
        self.assertEqual(self.f.get(r["id"])["name"], "Spotify")          # в архиве, не стёрта

    def test_bad_input(self):
        for args in (("", 5), ("X", "много"), ("X", -1)):
            with self.assertRaises(FinanceError):
                self.f.add(*args)

    def test_rates_parse_and_fallback(self):
        fin._rates.update(at=0, data=None)
        ok = mock.Mock(json=lambda: [{"Ccy": "USD", "Rate": "11994.10", "Nominal": "1"}, {"Ccy": "JPY", "Rate": "780", "Nominal": "10"}])
        t = fin.rates(now=1000, get=lambda *a, **k: ok)
        self.assertEqual((t["USD"], t["JPY"], t["UZS"]), (11994.10, 78.0, 1.0))
        broken = mock.Mock(side_effect=fin.requests.ConnectionError())
        self.assertEqual(fin.rates(now=1000 + 7 * 3600, get=broken)["USD"], 11994.10)   # нет связи — прошлый курс


class Tool(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(money, "finance", Finance(":memory:"))
        self.f = p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(fin, "rates", return_value=TABLE)
        p.start()
        self.addCleanup(p.stop)

    def test_registered(self):
        self.assertIn("subscriptions", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["subscriptions"], "finance")

    def test_add_list_total(self):
        out = money.tool_subscriptions({"action": "add", "name": "Token Plan", "amount": 10, "currency": "USD", "next_date": "2026-12-07"})
        self.assertIn("Записала", out)
        out = money.tool_subscriptions({"action": "list"})
        self.assertIn("Token Plan — $10 в месяц", out)
        self.assertIn("120 000 сум", out)
        self.assertIn("$10", money.tool_subscriptions({"action": "total"}))

    def test_stop_asks(self):
        self.f.add("A", 1, "USD")
        with mock.patch.object(money, "confirm", return_value=False):
            self.assertEqual(money.tool_subscriptions({"action": "stop", "name": "A"}), "Оставила.")
        with mock.patch.object(money, "confirm", return_value=True):
            self.assertIn("на сайте сервиса", money.tool_subscriptions({"action": "stop", "name": "A"}))

    def test_ambiguous(self):
        self.f.add("Яндекс Плюс", 1, "USD")
        self.f.add("Яндекс Диск", 1, "USD")
        self.assertIn("Нашла несколько", money.tool_subscriptions({"action": "edit", "name": "яндекс", "amount": 2}))

    def test_errors_are_friendly(self):
        self.assertIn("Не могу", money.tool_subscriptions({"action": "add", "name": "X", "amount": 1, "period": "иногда"}))
        self.assertIn("дата", money.tool_subscriptions({"action": "add", "name": "X", "amount": 1, "next_date": "завтра"}))


class Notices(unittest.TestCase):
    def test_startup_once_a_day_and_brief(self):
        settings.set("pay_notice_day", None)
        f = Finance(":memory:")
        today = datetime.date.today()
        f.add("Token Plan", 10, "USD", "month", (today + datetime.timedelta(days=1)).isoformat())
        with mock.patch("chloe.finance.finance", f):
            self.assertIn("Token Plan — $10 завтра", app.payment_notice())
            self.assertEqual(app.payment_notice(), "")                     # второй запуск за день — молчит
            self.assertIn("Скоро списания", tn._payments())


if __name__ == "__main__":
    unittest.main()
