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
    wake_word_threshold: float = 0.6
    wake_word_consecutive_frames: int = 2

    # Audio
    sample_rate: int = 16000
    channels: int = 1

    # TTS
    tts_voice: str = "amy"
    # Piper speech rate — lower is faster. 1.0 is model default, 0.9 is a snappier feel.
    tts_length_scale: float = 0.8

    # STT — tiny.en is ~3x faster than base on Pi 5 and plenty accurate for commands.
    stt_model_size: str = "tiny.en"

    # LLM
    llm_model: str = "gemini-2.5-flash-lite"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore unknown env vars


@lru_cache
def get_settings() -> Settings:
    return Settings()
