from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, RedisDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    ENV: Literal["local", "dev", "prod"] = "local"
    DEBUG: bool = False
    PROJECT_NAME: str = "fast-api"
    API_V1_PREFIX: str = "/api/v1"

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_JSON: bool = False

    POSTGIS_HOST: str = "localhost"
    POSTGIS_PORT: int = 5432
    POSTGIS_USER: str = "postgresql"
    POSTGIS_PASSWORD: str = "postgresql"
    POSTGIS_DB: str = "app"

    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    WORKER_DB_POOL_SIZE: int = 3

    ALERT_MODE: Literal["enter", "every_report"] = "enter"
    ALERT_COOLDOWN_S: float = 60.0

    GEOFENCE_BATCH_SIZE: int = 5_000
    GEOFENCE_BLOCK_MS: int = 1_000
    GEOFENCE_REPORT_INTERVAL_S: float = 10.0

    HISTORY_BATCH_SIZE: int = 5_000
    HISTORY_BLOCK_MS: int = 1_000

    HISTORY_PARTITION_AHEAD_DAYS: int = 2
    HISTORY_REPORT_INTERVAL_S: float = 10.0

    FD_SOFT_LIMIT: int = 65_536

    INGEST_BUFFER_MAXSIZE: int = 50_000
    INGEST_FLUSH_INTERVAL_MS: int = 150

    WS_CLIENT_QUEUE_MAXSIZE: int = 100

    MAP_BROADCAST_INTERVAL_MS: int = 1000

    INGEST_STREAM_MAXLEN: int = 200_000

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_MAX_CONNECTIONS: int = 20

    @computed_field
    @property
    def database_url(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.POSTGIS_USER,
            password=self.POSTGIS_PASSWORD,
            host=self.POSTGIS_HOST,
            port=self.POSTGIS_PORT,
            path=self.POSTGIS_DB,
        )

    @computed_field
    @property
    def redis_dsn(self) -> str:
        return str(
            RedisDsn.build(
                scheme="redis",
                host=self.REDIS_HOST,
                port=self.REDIS_PORT,
                password=self.REDIS_PASSWORD or None,
                path=str(self.REDIS_DB),
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
