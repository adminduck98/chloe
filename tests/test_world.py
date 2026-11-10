"""World Intelligence: источники подменены, сеть не нужна."""
import time
import unittest
from unittest import mock

from chloe import world
from chloe.permissions import TOOL_CATEGORY
from chloe.settings import settings
from chloe.tools import HANDLERS
from chloe.tools import world as tw

NOW = 1794300000.0


def ev(kind, title, lat, lon, age_h=1, level=1, source="S"):
    return world.event(kind, title, lat, lon, NOW - age_h * 3600, level, source)


class Parts(unittest.TestCase):
    def test_locate(self):
        self.assertEqual(world.locate("Здание в Ташкенте продали")[2], "Ташкент")
        self.assertEqual(world.locate("В Эстонии возмутились ультиматумом Германии")[2], "Эстония")
        self.assertEqual(world.locate("Из США в Узбекистан вернули мужчину", world.UZ)[2], "Узбекистан")
        self.assertIsNone(world.locate("Учёные открыли новый вид бабочек"))
        self.assertIsNone(world.locate("Доллар вырос, синдикат распался"))      # «инди» внутри слова — не Индия

    def test_distance(self):
        self.assertAlmostEqual(world.distance_km(41.3, 69.2, 39.65, 66.96), 265, delta=15)   # Ташкент — Самарканд

    def test_quakes_parse(self):
        data = {"features": [{"properties": {"mag": 6.7, "place": "Japan", "time": NOW * 1000, "url": "u", "tsunami": 1},
                              "geometry": {"coordinates": [140.0, 36.0, 24.2]}}]}
        with mock.patch.object(world, "_get", return_value=mock.Mock(json=lambda: data)):
            e = world.quakes()[0]
        self.assertEqual((e["kind"], e["lat"], e["lon"], e["level"]), ("quake", 36.0, 140.0, 3))
        self.assertIn("цунами", e["detail"])

    def test_gdacs_parse_skips_weak_quakes(self):
        xml = b"""<rss xmlns:gdacs="http://www.gdacs.org" xmlns:georss="http://www.georss.org/georss"><channel>
        <item><title>Green earthquake</title><pubDate>Tue, 10 Nov 2026 10:00:00 GMT</pubDate><georss:point>1 2</georss:point>
          <gdacs:eventtype>EQ</gdacs:eventtype><gdacs:alertlevel>Green</gdacs:alertlevel></item>
        <item><title>Orange   cyclone  X</title><pubDate>Tue, 10 Nov 2026 10:00:00 GMT</pubDate><georss:point>-10.5 165.5</georss:point>
          <gdacs:eventtype>TC</gdacs:eventtype><gdacs:alertlevel>Orange</gdacs:alertlevel><gdacs:country>Fiji</gdacs:country></item>
        </channel></rss>"""
        with mock.patch.object(world, "_get", return_value=mock.Mock(content=xml)):
            out = world.disasters()
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["kind"], out[0]["level"], out[0]["lat"], out[0]["title"]), ("cyclone", 2, -10.5, "Orange cyclone X"))

    def test_cyber_last_week_only(self):
        data = {"vulnerabilities": [
            {"cveID": "CVE-1", "vendorProject": "A", "product": "B", "vulnerabilityName": "new", "dateAdded": time.strftime("%Y-%m-%d", time.gmtime(NOW - 86400)),
             "knownRansomwareCampaignUse": "Known"},
            {"cveID": "CVE-0", "vendorProject": "A", "product": "B", "vulnerabilityName": "old", "dateAdded": "2020-01-01"}]}
        with mock.patch.object(world, "_get", return_value=mock.Mock(json=lambda: data)):
            out = world.cyber(now=NOW)
        self.assertEqual([v["id"] for v in out], ["CVE-1"])
        self.assertTrue(out[0]["ransomware"])


class Picture(unittest.TestCase):
    def setUp(self):
        settings.set("world_off", None)
        settings.set("city", {"name": "Ташкент", "lat": 41.26, "lon": 69.22})
        world._cache.update(at=0, data=None)
        fires = [ev("fire", "Fire %d" % i, -10 - i, 20, age_h=i + 1) for i in range(60)]
        self.fetch = {"quakes": lambda: [ev("quake", "M5 near", 40.0, 68.0, source="USGS"), ev("quake", "M7 far", -20.0, -70.0, level=3)],
                      "disasters": lambda: [ev("quake", "M5 near dup", 40.2, 68.3, source="GDACS", level=2), ev("drought", "old", 0, 0, age_h=24 * 100)],
                      "nature": lambda: fires, "news": lambda: (_ for _ in ()).throw(RuntimeError("нет сети"))}
        for target, name, val in ((world, "FETCH", self.fetch), (world, "markets", lambda: [{"name": "USD/UZS", "value": 12000.0, "change": 5.0}]),
                                  (world, "cyber", lambda: []), (world, "SNAPSHOT", world.DATA / "world-test.json")):
            p = mock.patch.object(world, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: settings.set("city", None))

    def test_merge_rules(self):
        p = world.picture(fresh=True, now=NOW)
        kinds = [e["kind"] for e in p["events"]]
        self.assertEqual(kinds.count("fire"), world.MAX_FIRES)                 # пожаров — не больше лимита
        self.assertNotIn("drought", kinds)                                     # событию 100 дней — не новость
        near = [e for e in p["events"] if e.get("near")]
        self.assertEqual(len(near), 1)                                         # одно землетрясение из двух источников — один раз
        self.assertEqual(near[0]["source"], "GDACS")                           # остаётся запись с более высокой тревогой
        self.assertEqual(p["events"][0]["title"], "M7 far")                    # самое серьёзное — первым
        self.assertEqual(p["failed"], [world.SOURCES["news"]])                 # сломанный источник не роняет картину
        self.assertTrue(world.SNAPSHOT.exists())
        self.assertTrue(world.clear())

    def test_sources_off(self):
        self.assertTrue(world.set_source("nature", False))
        p = world.picture(fresh=True, now=NOW)
        self.assertNotIn("fire", [e["kind"] for e in p["events"]])
        self.assertFalse(p["sources"]["nature"])
        self.assertFalse(world.set_source("нет такого", False))

    def test_tool(self):
        self.assertIn("world", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["world"], "news")
        with mock.patch.object(world.time, "time", return_value=NOW):
            out = tw.tool_world({"fresh": True})
            self.assertTrue(out.startswith(tw.NOTE))
            self.assertIn("M7 far", out)
            self.assertIn("Рядом с вами (Ташкент", out)
            self.assertIn("USD/UZS", out)
            self.assertIn("оценка", out)
            self.assertIn("M5 near", tw.tool_world({"action": "events", "near": True}))
        self.assertIn("выкл", tw.tool_world({"action": "sources", "source": "киберугрозы", "on": False}))
        self.assertIn("Такого источника нет", tw.tool_world({"action": "sources", "source": "погода", "on": True}))


if __name__ == "__main__":
    unittest.main()
