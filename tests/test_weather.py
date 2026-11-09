"""Город и погода. Сеть подменена: ответы Open-Meteo — заготовки, настройки — во временной домашней папке."""
import unittest
from unittest import mock

from chloe import config
from chloe.settings import settings
from chloe.thinking.prompt import system_prompt
from chloe.thinking.router import Route
from chloe.tools import run_tool
from chloe.tools import weather
from chloe.voice import voice

voice.enabled = False

GEO = {"results": [
    {"name": "Ташкент", "country": "Узбекистан", "admin1": "Ташкент", "latitude": 41.26, "longitude": 69.21, "timezone": "Asia/Tashkent"},
    {"name": "Ташкент", "country": "Россия", "admin1": "Башкортостан", "latitude": 56.31, "longitude": 55.40, "timezone": "Asia/Yekaterinburg"},
]}
FORECAST = {
    "current": {"time": "2026-11-05T13:15", "temperature_2m": 11.8, "apparent_temperature": 9.6, "weather_code": 61,
                "wind_speed_10m": 3.4, "relative_humidity_2m": 80},
    "daily": {"time": ["2026-11-05", "2026-11-06", "2026-11-07"], "weather_code": [61, 3, 0],
              "temperature_2m_max": [14.2, 16.0, 18.4], "temperature_2m_min": [7.9, -0.4, 5.0],
              "precipitation_probability_max": [90, 10, None]},
}


def fake_get(url, params):
    if url == weather.GEO_URL:
        return GEO if params["name"] == "Ташкент" else {}
    fake_get.forecast_params = params
    return FORECAST


class Weather(unittest.TestCase):
    def setUp(self):
        settings.path.unlink(missing_ok=True)
        patcher = mock.patch.object(weather, "get_json", side_effect=fake_get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unknown_city_asks_user(self):
        out, _, failed = run_tool("weather", {})
        self.assertTrue(failed)
        self.assertIn("set_city", out)
        self.assertIn("пока неизвестен", system_prompt())

    def test_set_city_then_weather(self):
        out, _, failed = run_tool("set_city", {"city": "Ташкент"})
        self.assertFalse(failed)
        self.assertIn("Узбекистан", out)
        self.assertIn("Город пользователя: Ташкент, Узбекистан", system_prompt())
        out, _, failed = run_tool("weather", {})
        self.assertFalse(failed, out)
        self.assertEqual(fake_get.forecast_params["latitude"], 41.26)
        self.assertIn("небольшой дождь, +12° (ощущается +10°)", out)
        self.assertIn("завтра 06.11: пасмурно, от 0° до +16°", out)
        self.assertIn("суббота 07.11: ясно", out)   # день недели, а не «послезавтра»
        self.assertNotIn("None", out)

    def test_country_picks_the_right_place(self):
        run_tool("set_city", {"city": "Ташкент, Россия"})
        self.assertEqual(settings.get("city")["region"], "Башкортостан")

    def test_other_city_does_not_change_home(self):
        run_tool("set_city", {"city": "Ташкент"})
        out, _, failed = run_tool("weather", {"city": "Атлантида"})
        self.assertTrue(failed)
        self.assertEqual(settings.get("city")["country"], "Узбекистан")

    def test_days_limited(self):
        run_tool("set_city", {"city": "Ташкент"})
        run_tool("weather", {"days": 30})
        self.assertEqual(fake_get.forecast_params["forecast_days"], 7)

    def test_weather_is_a_fast_brain_job(self):
        config.MODEL_FAST, config.MODEL_STRONG = "fast-model", "strong-model"
        r = Route("какая погода завтра")
        self.assertEqual(r.model, "fast-model")
        self.assertFalse(r.redo_for(["weather", "set_city"]))


if __name__ == "__main__":
    unittest.main()
