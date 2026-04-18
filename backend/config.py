from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Google ADK
    google_api_key: str = ""

    # Weather (uses Open-Meteo, no API key needed)
    weather_lat: float = 40.7128  # New York
    weather_lon: float = -74.0060

    # Wake word
    wake_word: str = "hey_jarvis"

    # Audio
    sample_rate: int = 16000
    channels: int = 1

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore unknown env vars


@lru_cache
def get_settings() -> Settings:
    return Settings()
