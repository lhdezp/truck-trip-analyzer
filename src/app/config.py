"""Centralised, validated application configuration.

Every environment variable is declared exactly once here. Modules must read
configuration through :func:`get_settings` instead of touching ``os.environ``.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.exceptions import ConfigurationError


class AppEnvironment(StrEnum):
    """Supported runtime environments."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


_PROVIDER_SECRETS = (
    "API_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "GEMINI_API_KEY",
    "FREIGHT_DATAWATCH_API_KEY",
    "OPENROUTESERVICE_API_KEY",
)


class Settings(BaseSettings):
    """Typed view of the environment.

    Secrets are wrapped in :class:`~pydantic.SecretStr` so they are never
    rendered by logs, ``repr`` or tracebacks. In development they may stay
    empty; in production the validator below refuses to start without them.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=True,
    )

    APP_ENV: AppEnvironment = AppEnvironment.DEVELOPMENT
    APP_NAME: str = "Truck Load Analyzer"
    APP_DEBUG: bool = False

    API_SECRET: SecretStr | None = None

    TELEGRAM_BOT_TOKEN: SecretStr | None = None
    TELEGRAM_ALLOWED_USERS: str = ""

    AI_PROVIDER: Literal["gemini"] = "gemini"
    GEMINI_API_KEY: SecretStr | None = None
    GEMINI_MODEL: str = ""
    GEMINI_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0, le=300)
    MAX_IMAGES_PER_ANALYSIS: int = Field(default=6, ge=1, le=20)

    MARKET_PROVIDER: Literal["freight_datawatch"] = "freight_datawatch"
    FREIGHT_DATAWATCH_API_KEY: SecretStr | None = None
    FREIGHT_DATAWATCH_BASE_URL: str = "https://app.freightdatawatch.com/api/v1"

    WEATHER_PROVIDER: Literal["nws"] = "nws"

    MAPS_PROVIDER: Literal["openrouteservice"] = "openrouteservice"
    OPENROUTESERVICE_API_KEY: SecretStr | None = None

    DATABASE_URL: str = "sqlite:///./truck_analyzer.db"
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    @field_validator("TELEGRAM_ALLOWED_USERS")
    @classmethod
    def _validate_allowed_users(cls, value: str) -> str:
        for raw in value.split(","):
            candidate = raw.strip()
            if candidate and not candidate.isdigit():
                raise ValueError(
                    "TELEGRAM_ALLOWED_USERS must be a comma separated list of numeric "
                    f"Telegram user IDs, got {candidate!r}"
                )
        return value

    @field_validator("FREIGHT_DATAWATCH_BASE_URL")
    @classmethod
    def _validate_market_base_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("FREIGHT_DATAWATCH_BASE_URL must use https")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _require_production_settings(self) -> Settings:
        if self.APP_ENV is not AppEnvironment.PRODUCTION:
            return self

        missing = [name for name in _PROVIDER_SECRETS if getattr(self, name) is None]
        if not self.GEMINI_MODEL:
            missing.append("GEMINI_MODEL")
        if not self.telegram_allowed_user_ids:
            missing.append("TELEGRAM_ALLOWED_USERS")

        if missing:
            raise ConfigurationError(
                "Missing required configuration for production: " + ", ".join(missing)
            )
        return self

    @property
    def telegram_allowed_user_ids(self) -> tuple[int, ...]:
        """Allowed Telegram user IDs as integers."""
        return tuple(
            int(raw.strip()) for raw in self.TELEGRAM_ALLOWED_USERS.split(",") if raw.strip()
        )

    def safe_summary(self) -> dict[str, object]:
        """Configuration snapshot that is safe to log: no secret values."""
        secrets = {name: getattr(self, name) for name in _PROVIDER_SECRETS}
        return {
            "app_name": self.APP_NAME,
            "app_env": self.APP_ENV.value,
            "app_debug": self.APP_DEBUG,
            "ai_provider": self.AI_PROVIDER,
            "gemini_model": self.GEMINI_MODEL or None,
            "max_images_per_analysis": self.MAX_IMAGES_PER_ANALYSIS,
            "market_provider": self.MARKET_PROVIDER,
            "market_base_url": self.FREIGHT_DATAWATCH_BASE_URL,
            "maps_provider": self.MAPS_PROVIDER,
            "weather_provider": self.WEATHER_PROVIDER,
            "database_url": self.DATABASE_URL,
            "secrets_configured": {name: value is not None for name, value in secrets.items()},
        }


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance, built once."""
    return Settings()
