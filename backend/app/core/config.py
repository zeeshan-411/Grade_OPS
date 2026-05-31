from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    POSTGRES_USER: str = "gradeops"
    POSTGRES_PASSWORD: str = "gradeops_dev_pw"
    POSTGRES_DB: str = "gradeops"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    ALGORITHM: str = "HS256"

    # Comma-separated string (pydantic-settings JSON-decodes list types, so we
    # keep it as a string and split via the cors_origins property).
    BACKEND_CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    STORAGE_ROOT: str = "/data"

    # Storage backend: "local" writes under STORAGE_ROOT, "gcs" writes to the
    # GCS bucket below using GOOGLE_APPLICATION_CREDENTIALS.
    STORAGE_BACKEND: str = "local"
    GCS_BUCKET: str = ""
    GCS_PREFIX: str = "gradeops"

    # OCR engine for real grading (DEMO_MODE bypasses OCR entirely).
    #   "gemini" — Google Gemini Vision (default, requires GEMINI_API_KEY)
    #   "nougat" — facebook/nougat-small via the ml-worker container
    OCR_ENGINE: str = "gemini"
    ML_WORKER_URL: str = "http://ml-worker:8001"

    # When true, /grade synthesizes plausible grades from the rubric (no OCR, no
    # LLM calls). Lets the UI demo end-to-end when the Gemini free-tier quota is
    # exhausted.
    DEMO_MODE: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def database_url_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        # Alembic uses sync driver
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
