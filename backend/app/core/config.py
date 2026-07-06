"""Application settings for the SpeakHan backend.

All environment-driven configuration is declared here so the rest of the app
can depend on typed settings instead of reading environment variables directly.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings loaded from defaults, environment, and .env."""

    APP_NAME: str = "SpeakHan / Mandarin Memory Coach"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./memory.db"
    STORAGE_DIR: str = "./storage"
    USER_AUDIO_DIR: str = "./storage/user_audio"
    TUTOR_AUDIO_DIR: str = "./storage/tutor_audio"
    USE_FAKE_QWEN: bool = True
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = ""
    QWEN_CHAT_MODEL: str = ""
    QWEN_ASR_MODEL: str = ""
    QWEN_TTS_MODEL: str = ""
    QWEN_REQUEST_TIMEOUT_SECONDS: float = 45.0
    QWEN_MAX_TUTOR_TOKENS: int = 180
    QWEN_MAX_ANALYSIS_TOKENS: int = 650
    QWEN_MAX_TURN_TOKENS: int = 900
    MAX_AUDIO_UPLOAD_BYTES: int = 5_000_000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def database_type(self) -> str:
        """Return the database driver prefix for health and diagnostics."""
        return self.DATABASE_URL.split(":", maxsplit=1)[0]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings so app code uses one consistent configuration."""
    return Settings()
