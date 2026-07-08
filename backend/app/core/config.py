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
    PUBLIC_BACKEND_BASE_URL: str = ""
    ALIBABA_OSS_ACCESS_KEY_ID: str = ""
    ALIBABA_OSS_ACCESS_KEY_SECRET: str = ""
    ALIBABA_OSS_ENDPOINT: str = ""
    ALIBABA_OSS_BUCKET: str = ""
    ALIBABA_OSS_PUBLIC_BASE_URL: str = ""
    ALIBABA_OSS_PREFIX: str = "speechan/audio/"
    ALIBABA_OSS_SIGNED_URL_EXPIRES_SECONDS: int = 900
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_ENDPOINT_URL: str = ""
    S3_BUCKET: str = ""
    S3_REGION: str = "auto"
    S3_PUBLIC_BASE_URL: str = ""
    S3_PREFIX: str = "speechan/audio/"
    S3_SIGNED_URL_EXPIRES_SECONDS: int = 900
    USE_FAKE_QWEN: bool = True
    USE_FAKE_ASR: bool = True
    USE_FAKE_TTS: bool = True
    QWEN_API_KEY: str = ""
    DASHSCOPE_API_KEY: str = ""
    QWEN_BASE_URL: str = ""
    QWEN_CHAT_MODEL: str = ""
    QWEN_ASR_BASE_URL: str = ""
    QWEN_ASR_MODEL: str = "qwen3-asr-flash"
    QWEN_ASR_LANGUAGE: str = "zh"
    QWEN_ASR_ENABLE_LID: bool = True
    QWEN_ASR_ENABLE_ITN: bool = False
    QWEN_ASR_AUDIO_REF_MODE: str = "oss_url"
    QWEN_ASR_REQUEST_TIMEOUT_SECONDS: float = 30.0
    QWEN_ASR_MAX_RETRIES: int = 0
    QWEN_TTS_MODEL: str = ""
    QWEN_TTS_VOICE: str = ""
    QWEN_TTS_BASE_URL: str = ""
    QWEN_TTS_OUTPUT_FORMAT: str = "mp3"
    REALTIME_TTS_MAX_CONCURRENCY: int = 1
    SSL_CERT_FILE: str = ""
    REQUESTS_CA_BUNDLE: str = ""
    QWEN_REQUEST_TIMEOUT_SECONDS: float = 30.0
    QWEN_MAX_TUTOR_TOKENS: int = 180
    QWEN_MAX_ANALYSIS_TOKENS: int = 650
    QWEN_MAX_TURN_TOKENS: int = 500
    QWEN_MAX_RETRIES: int = 0
    MAX_AUDIO_UPLOAD_BYTES: int = 5_000_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_type(self) -> str:
        """Return the database driver prefix for health and diagnostics."""
        return self.DATABASE_URL.split(":", maxsplit=1)[0]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings so app code uses one consistent configuration."""
    return Settings()
