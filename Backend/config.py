from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    shared_root: Path = Path("/mnt/tank/family_share")
    app_secret: str
    auth_db_path: Path = Path("/mnt/auth/auth.sqlite3")
    session_hours: int = 24
    cookie_secure: bool = True
    public_origin: str = "https://files.example.com"

    @field_validator("app_secret")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("APP_SECRET must be at least 32 characters")
        return value

    @field_validator("shared_root", "auth_db_path")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Filesystem paths must be absolute")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
