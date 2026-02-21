"""
Centralized configuration management for ScaleScore.

This module implements ADR-0009: Configuration Management.
All application settings are defined here using pydantic-settings.

Configuration hierarchy (highest to lowest priority):
1. Environment variables
2. .env file
3. Default values

Usage:
    from scalescore.config import settings

    # Access settings
    print(settings.app_name)
    print(settings.database.host)

    # Check environment
    if settings.is_production():
        # Production-specific behavior
        pass
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = "localhost"
    port: int = 5432
    name: str = "scalescore"
    user: str = "scalescore"
    password: SecretStr = Field(default=SecretStr(""))
    pool_size: int = Field(default=5, ge=1, le=50)
    pool_overflow: int = Field(default=10, ge=0, le=50)
    echo: bool = False  # SQL logging

    @property
    def url(self) -> str:
        """Construct database URL (without password for logging)."""
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.name}"

    @property
    def async_url(self) -> str:
        """Construct async database URL (without password for logging)."""
        return f"postgresql+asyncpg://{self.user}@{self.host}:{self.port}/{self.name}"

    def get_url_with_password(self) -> str:
        """Construct full database URL with password."""
        password = self.password.get_secret_value()
        if password:
            return f"postgresql://{self.user}:{password}@{self.host}:{self.port}/{self.name}"
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.name}"

    def get_async_url_with_password(self) -> str:
        """Construct full async database URL with password."""
        password = self.password.get_secret_value()
        if password:
            return f"postgresql+asyncpg://{self.user}:{password}@{self.host}:{self.port}/{self.name}"
        return f"postgresql+asyncpg://{self.user}@{self.host}:{self.port}/{self.name}"


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    model_config = SettingsConfigDict(env_prefix="AUTH_")

    # JWT settings
    jwt_secret: SecretStr = Field(default=SecretStr("CHANGE_ME_IN_PRODUCTION"))
    jwt_algorithm: str = "RS256"
    jwt_private_key_path: str | None = None
    jwt_public_key_path: str | None = None

    # Token expiration
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)

    # Development mode
    skip_auth: bool = Field(
        default=False,
        description="Skip authentication in development (NEVER enable in production)",
    )


class ScoringSettings(BaseSettings):
    """Scoring engine configuration."""

    model_config = SettingsConfigDict(env_prefix="SCORING_")

    # Base scoring
    base_score: float = Field(default=100.0, ge=0, le=100)
    assessment_version: str = "1.0"

    # Growth settings
    growth_multiplier_cap: float = Field(default=2.0, ge=1.0, le=5.0)
    trend_delta_threshold: float = Field(default=1.0, ge=0.0)

    # Constraint severity weights
    capacity_severity: float = Field(default=15.0, ge=0)
    dependency_severity: float = Field(default=12.0, ge=0)
    governance_severity: float = Field(default=8.0, ge=0)
    financial_severity: float = Field(default=20.0, ge=0)
    talent_severity: float = Field(default=10.0, ge=0)
    timeline_severity: float = Field(default=5.0, ge=0)

    # Risk level multipliers
    risk_low_multiplier: float = Field(default=0.5, ge=0)
    risk_medium_multiplier: float = Field(default=1.0, ge=0)
    risk_high_multiplier: float = Field(default=1.5, ge=0)
    risk_critical_multiplier: float = Field(default=2.5, ge=0)


class FeatureFlags(BaseSettings):
    """Feature flag configuration for gradual rollout."""

    model_config = SettingsConfigDict(env_prefix="FEATURE_")

    # Core features
    enable_recommendations: bool = True
    enable_bottleneck_detection: bool = True
    enable_dependency_graph: bool = True

    # Platform features (disabled until implemented)
    enable_multi_tenant: bool = False
    enable_async_assessments: bool = False
    enable_scheduled_assessments: bool = False

    # Observability
    enable_telemetry: bool = False
    enable_audit_logging: bool = True


class ServerSettings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(env_prefix="SERVER_")

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=32)
    reload: bool = False  # Auto-reload on code changes (dev only)


class StorageSettings(BaseSettings):
    """Local storage settings used for persisted assessment snapshots."""

    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    assessments_db_path: str = ".local/scalescore/assessments.sqlite3"
    auth_db_path: str = ".local/scalescore/auth.sqlite3"
    # Backward-compatible override for deployments still using the old variable name.
    refresh_tokens_db_path: str | None = None

    @property
    def effective_auth_db_path(self) -> str:
        return self.refresh_tokens_db_path or self.auth_db_path


class IntegrationSettings(BaseSettings):
    """Integration settings for external systems (for example OpsOrchestra)."""

    model_config = SettingsConfigDict(env_prefix="INTEGRATION_")

    opsorchestra_webhook_secret: SecretStr | None = None


class Settings(BaseSettings):
    """
    Main application settings.

    All settings can be overridden via environment variables.
    Nested settings use double underscore: DATABASE__HOST=myhost
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # Application identity
    app_name: str = "ScaleScore"
    app_version: str = "0.1.0"

    # Environment
    environment: str = Field(
        default="development",
        pattern=r"^(development|staging|production|testing)$",
    )
    debug: bool = False

    # Logging
    log_level: str = Field(
        default="INFO",
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
    )
    log_format: str = Field(
        default="json",
        pattern=r"^(json|text)$",
    )

    # Nested settings
    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    integration: IntegrationSettings = Field(default_factory=IntegrationSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)

    # Optional: OpenTelemetry endpoint
    otlp_endpoint: str | None = None

    @field_validator("debug")
    @classmethod
    def validate_debug_not_in_production(cls, v: bool, info: Any) -> bool:
        """Prevent debug mode in production."""
        # Note: We can't access other fields in field_validator
        # This validation happens in model_validator instead
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Validate settings specific to production environment."""
        if self.environment == "production":
            # Debug must be off
            if self.debug:
                raise ValueError("Debug mode cannot be enabled in production")

            # Auth skip must be off
            if self.auth.skip_auth:
                raise ValueError("Authentication cannot be skipped in production")

            # JWT secret must be changed
            if self.auth.jwt_secret.get_secret_value() == "CHANGE_ME_IN_PRODUCTION":
                raise ValueError(
                    "JWT secret must be set in production (AUTH_JWT_SECRET)"
                )

        return self

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"

    def is_testing(self) -> bool:
        """Check if running in testing environment."""
        return self.environment == "testing"

    def get_log_config(self) -> dict[str, Any]:
        """Get logging configuration dictionary."""
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
                "json": {
                    "class": "pythonjsonlogger.jsonlogger.JsonFormatter"
                    if self.log_format == "json"
                    else "logging.Formatter",
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default" if self.log_format == "text" else "json",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": self.log_level,
                "handlers": ["default"],
            },
        }


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Settings are loaded once and cached for the lifetime of the application.
    """
    return Settings()


# Convenience accessor - import this for direct access
settings = get_settings()
