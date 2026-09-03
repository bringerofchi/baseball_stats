"""
Optional weather enrichment client.

MLB stadium weather affects run-scoring environments (wind blowing out at
Wrigley, humidity, etc.), which is a legitimate input to totals-related
edges. This uses a generic REST weather provider interface — plug in
OpenWeatherMap, Tomorrow.io, or Visual Crossing by adjusting BASE_URL and
the response parsing in _parse().

If WEATHER_API_KEY is unset or MOCK_MODE is True, returns synthetic data.
"""
import requests

import config

# Rough stadium coordinates for outdoor parks (extend as needed).
STADIUM_COORDS = {
    "Yankee Stadium": (40.8296, -73.9262),
    "Fenway Park": (42.3467, -71.0972),
    "Dodger Stadium": (34.0739, -118.2400),
    "Oracle Park": (37.7786, -122.3893),
    "Wrigley Field": (41.9484, -87.6553),
}


class WeatherClient:
    def __init__(self, api_key: str = None, mock_mode: bool = None):
        self.api_key = api_key or config.WEATHER_API_KEY
        self.mock_mode = config.MOCK_MODE if mock_mode is None else mock_mode

    def get_weather_for_stadium(self, stadium: str, date_str: str):
        if self.mock_mode or not self.api_key:
            return self._mock_weather(stadium)

        coords = STADIUM_COORDS.get(stadium)
        if not coords:
            return self._mock_weather(stadium)

        lat, lon = coords
        # Example using OpenWeatherMap-style API; swap for your provider.
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": self.api_key, "units": "imperial"},
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return self._parse(resp.json())

    def _parse(self, raw: dict):
        return {
            "weather_temp": raw.get("main", {}).get("temp"),
            "weather_wind_speed": raw.get("wind", {}).get("speed"),
            "weather_wind_direction": self._deg_to_compass(raw.get("wind", {}).get("deg")),
            "weather_precipitation": raw.get("rain", {}).get("1h", 0.0),
        }

    @staticmethod
    def _deg_to_compass(deg):
        if deg is None:
            return None
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        return dirs[int((deg / 45) % 8)]

    def _mock_weather(self, stadium: str):
        return {
            "weather_temp": 78.0,
            "weather_wind_speed": 8.0,
            "weather_wind_direction": "SW",
            "weather_precipitation": 0.0,
        }
