from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite:///.data/app.db"
    qdrant_path: str = ".data/qdrant"
    qdrant_url: str | None = (
        None  # If set, use HTTP transport (e.g., "http://127.0.0.1:6333")
    )
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_cache_dir: str = ".data/models"
    cf_account_id: str | None = None
    cf_api_token: str | None = None
    poll_interval_seconds: int = 10
    scheduler_interval_seconds: int = 60
    job_timeout_minutes: int = 30
    chunk_target_chars: int = 800
    chunk_overlap_chars: int = 120
    default_crawl_depth: int = 1
    default_crawl_limit: int = 50
    default_formats: list[str] = ["markdown"]
    default_source_type: str = "docs"
    collection_name: str = "crawl_chunks"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.removeprefix("sqlite:///"))

    @property
    def qdrant_dir(self) -> Path:
        return Path(self.qdrant_path)

    @property
    def embedding_cache_path(self) -> Path:
        return Path(self.embedding_cache_dir)

    @property
    def cloudflare_enabled(self) -> bool:
        return bool(self.cf_account_id and self.cf_api_token)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.qdrant_dir.mkdir(parents=True, exist_ok=True)
    settings.embedding_cache_path.mkdir(parents=True, exist_ok=True)
    return settings
