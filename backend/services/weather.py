import httpx
from backend.config import get_settings


# WMO Weather Codes: https://open-meteo.com/en/docs
WMO_CODES = {
    0: ("Clear sky", "01d"),
    1: ("Mainly clear", "01d"),
    2: ("Partly cloudy", "02d"),
    3: ("Overcast", "03d"),
    45: ("Foggy", "50d"),
    48: ("Rime fog", "50d"),
    51: ("Light drizzle", "09d"),
    53: ("Moderate drizzle", "09d"),
    55: ("Dense drizzle", "09d"),
    61: ("Slight rain", "10d"),
    63: ("Moderate rain", "10d"),
    65: ("Heavy rain", "10d"),
    66: ("Light freezing rain", "13d"),
    67: ("Heavy freezing rain", "13d"),
    71: ("Slight snow", "13d"),
    73: ("Moderate snow", "13d"),
    75: ("Heavy snow", "13d"),
    77: ("Snow grains", "13d"),
    80: ("Slight rain showers", "09d"),
    81: ("Moderate rain showers", "09d"),
    82: ("Violent rain showers", "09d"),
    85: ("Slight snow showers", "13d"),
    86: ("Heavy snow showers", "13d"),
    95: ("Thunderstorm", "11d"),
    96: ("Thunderstorm with hail", "11d"),
    99: ("Thunderstorm with heavy hail", "11d"),
}


class WeatherService:
    """Fetch weather data from Open-Meteo (no API key needed)."""

    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self):
        self.settings = get_settings()

    async def get_current(self) -> dict:
        """Get current weather."""
        params = {
            "latitude": self.settings.weather_lat,
            "longitude": self.settings.weather_lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code",
            "temperature_unit": "celsius",
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()

            current = data["current"]
            code = current.get("weather_code", 0)
            description, icon = WMO_CODES.get(code, ("Unknown", "03d"))

            temp_c = round(current["temperature_2m"])
            temp_f = round(temp_c * 9 / 5 + 32)
            feels_c = round(current["apparent_temperature"])
            feels_f = round(feels_c * 9 / 5 + 32)

            return {
                "temp_c": temp_c,
                "temp_f": temp_f,
                "feels_like_c": feels_c,
                "feels_like_f": feels_f,
                "humidity": current.get("relative_humidity_2m", 0),
                "description": description,
                "icon": icon,
            }

        except httpx.HTTPError as e:
            return {"error": f"Failed to fetch weather: {e}"}
        except (KeyError, ValueError) as e:
            return {"error": f"Invalid weather data: {e}"}
