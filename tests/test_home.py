"""Home Assistant: подменённый сервер — комнаты, поиск устройства, риск по виду, вопрос «да/нет», «только смотреть»."""
import os
import unittest
from unittest import mock

from chloe import home as ha
from chloe.permissions import TOOL_CATEGORY, permissions
from chloe.settings import settings
from chloe.tools import HANDLERS
from chloe.tools import house

STATES = [
    {"entity_id": "light.gostinaia", "state": "off", "attributes": {"friendly_name": "Свет в гостиной"}},
    {"entity_id": "light.kukhnia", "state": "on", "attributes": {"friendly_name": "Свет на кухне", "brightness": 128}},
    {"entity_id": "lock.vkhod", "state": "locked", "attributes": {"friendly_name": "Входная дверь"}},
    {"entity_id": "climate.kondei", "state": "cool", "attributes": {"friendly_name": "Кондиционер", "current_temperature": 26, "temperature": 24}},
    {"entity_id": "switch.kotel", "state": "on", "attributes": {"friendly_name": "Котёл"}},
    {"entity_id": "sensor.temp", "state": "23.5", "attributes": {"friendly_name": "Температура в спальне", "unit_of_measurement": "°C"}},
    {"entity_id": "scene.kino", "state": "scening", "attributes": {"friendly_name": "Кино"}},
]
AREAS = {"light.gostinaia": "Гостиная", "light.kukhnia": "Кухня", "climate.kondei": "Гостиная", "sensor.temp": "Спальня"}


class FakeHA:
    def __init__(self):
        self.calls = []

    def request(self, method, url, json=None, timeout=None, headers=None):
        self.calls.append((method, url.split("8123")[1], json, headers["Authorization"]))
        path = url.split("8123")[1]
        if path == "/api/":
            return self.resp({"message": "API running."})
        if path == "/api/states":
            return self.resp(STATES)
        if path == "/api/template":
            return self.resp(__import__("json").dumps(AREAS))
        if path.startswith("/api/services/"):
            eid = json["entity_id"]
            return self.resp([{"entity_id": eid, "state": "on" if "turn_on" in path else "off"}])
        return self.resp({}, 404)

    @staticmethod
    def resp(data, code=200):
        r = mock.Mock(status_code=code)
        r.json.return_value = data
        r.text = data if isinstance(data, str) else ""
        return r


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeHA()
        for target, name, val in ((ha, "requests", mock.Mock(request=self.fake.request, RequestException=Exception)),):
            p = mock.patch.object(target, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"HA_URL": "http://ha.local:8123", "HA_TOKEN": "secret-token", "CHLOE_HOME_READONLY": ""})
        p.start()
        self.addCleanup(p.stop)
        settings.set("safe_mode", False)
        settings.set("connectors_off", None)


class Core(Base):
    def test_states_with_rooms_and_find(self):
        items = ha.states()
        self.assertEqual(next(i for i in items if i["entity_id"] == "light.gostinaia")["area"], "Гостиная")
        self.assertEqual([i["entity_id"] for i in ha.find("свет в гостиной", items)], ["light.gostinaia"])
        self.assertEqual([i["entity_id"] for i in ha.find("кондиционер", items)], ["climate.kondei"])
        self.assertEqual(len(ha.find("свет", items)), 2)
        self.assertEqual(self.fake.calls[0][3], "Bearer secret-token")

    def test_risk(self):
        items = {i["entity_id"]: i for i in ha.states()}
        self.assertEqual(ha.risk(items["light.gostinaia"], "turn_on")[0], "low")
        self.assertEqual(ha.risk(items["lock.vkhod"], "turn_off")[0], "ask")
        self.assertEqual(ha.risk(items["switch.kotel"], "turn_off")[0], "ask")          # «котёл» в названии
        self.assertEqual(ha.risk(items["climate.kondei"], "set_temperature", {"temperature": 22})[0], "low")
        self.assertEqual(ha.risk(items["climate.kondei"], "set_temperature", {"temperature": 35})[0], "ask")
        self.assertEqual(ha.risk(items["sensor.temp"], "turn_on")[0], "block")
        with mock.patch.dict(os.environ, {"CHLOE_HOME_READONLY": "1"}):
            self.assertEqual(ha.risk(items["light.gostinaia"], "turn_on")[0], "block")

    def test_not_configured(self):
        with mock.patch.dict(os.environ, {"HA_URL": "", "HA_TOKEN": ""}):
            self.assertEqual(ha.status_text()[0], "off")
            with self.assertRaises(ha.HomeError):
                ha.states()


class Tool(Base):
    def test_light_at_once_lock_asks(self):
        self.assertIn("home", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["home"], "home")
        with mock.patch.object(house, "confirm") as c:
            out = house.tool_home({"action": "on", "device": "свет в гостиной"})
        c.assert_not_called()
        self.assertIn("Готово", out)
        self.assertEqual(self.fake.calls[-1][1], "/api/services/light/turn_on")
        with mock.patch.object(house, "confirm", return_value=False) as c:
            self.assertEqual(house.tool_home({"action": "off", "device": "входная дверь"}), "Не стала.")
        self.assertIn("Открыть «Входная дверь»", c.call_args[0][0])         # замок: «выключить» — значит открыть
        self.assertIn("Замок", c.call_args[0][0])
        self.assertFalse(any("/lock/" in x[1] for x in self.fake.calls))
        with mock.patch.object(house, "confirm", return_value=True):
            house.tool_home({"action": "off", "device": "входная дверь"})
        self.assertEqual(self.fake.calls[-1][1], "/api/services/lock/unlock")

    def test_set_and_lists(self):
        house.tool_home({"action": "set", "device": "кухня свет", "brightness": 40})
        self.assertEqual(self.fake.calls[-1][2], {"brightness_pct": 40, "entity_id": "light.kukhnia"})
        rooms = house.tool_home({"action": "rooms"})
        self.assertIn("Гостиная:", rooms)
        self.assertIn("Температура в спальне: 23.5 °C", house.tool_home({"action": "state", "device": "температура"}))
        self.assertIn("Подходят несколько", house.tool_home({"action": "on", "device": "свет"}))
        self.assertIn("датчик", house.tool_home({"action": "on", "device": "температура в спальне"}))

    def test_safe_mode_and_connector_off_block(self):
        settings.set("safe_mode", True)
        self.assertEqual(permissions.check("home", {"action": "on"})[0], "block")
        settings.set("safe_mode", False)
        from chloe import connectors

        connectors.set_on("home_assistant", False)
        self.assertEqual(permissions.check("home", {"action": "on"})[0], "block")
        connectors.set_on("home_assistant", True)
        settings.set("connectors_off", None)

    def test_token_never_in_output(self):
        out = house.tool_home({"action": "status"}) + house.tool_home({"action": "rooms"})
        self.assertNotIn("secret-token", out)
        self.assertEqual(permissions.check("run_command", {"command": "echo $HA_TOKEN"})[0], "block")


if __name__ == "__main__":
    unittest.main()
