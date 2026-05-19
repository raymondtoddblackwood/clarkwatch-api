"""Env-driven configuration. Validated at startup so a missing var fails loud."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "clarkwatch-api"
    log_level: str = "INFO"
    port: int = 8080

    clarkwatch_api_secret: str

    supabase_url: str
    supabase_service_role_key: str

    cors_allowed_origins: str = "https://clark.dbnr.ai,https://dbnr.info,http://localhost:8000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
