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
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from scalescore.core.network import validate_remote_url


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
    public_signup_enabled: bool = Field(
        default=False,
        description="Allow public signup in production. Keep disabled unless enrollment is gated.",
    )
    login_rate_limit_requests: int = Field(default=120, ge=1, le=5000)
    login_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    signup_rate_limit_requests: int = Field(default=30, ge=1, le=1000)
    signup_rate_limit_window_seconds: int = Field(default=3600, ge=1, le=86_400)
    refresh_rate_limit_requests: int = Field(default=120, ge=1, le=5000)
    refresh_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)


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


class AsyncAssessmentSettings(BaseSettings):
    """Configuration for async assessment queue execution and abuse controls."""

    model_config = SettingsConfigDict(env_prefix="ASYNC_ASSESSMENT_")

    mode: Literal["poll", "background", "broker"] = "poll"
    worker_poll_interval_seconds: float = Field(default=0.25, ge=0.01, le=30.0)
    broker_url: str | None = None
    broker_queue_name: str = Field(
        default="scalescore:async-assessment:jobs",
        min_length=1,
        max_length=256,
    )
    broker_dequeue_timeout_seconds: int = Field(default=5, ge=1, le=60)
    scheduled_dispatch_poll_interval_seconds: float = Field(default=30.0, ge=1.0, le=3600.0)
    scheduled_dispatch_batch_size: int = Field(default=10, ge=1, le=500)
    submit_rate_limit_requests: int = Field(default=60, ge=1, le=5000)
    submit_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    max_outstanding_jobs_per_tenant: int = Field(default=25, ge=1, le=10_000)
    max_upload_bytes_per_file: int = Field(default=5_000_000, ge=1024, le=100_000_000)

    @field_validator("broker_url")
    @classmethod
    def validate_broker_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError(
                "ASYNC_ASSESSMENT_BROKER_URL must start with redis:// or rediss://"
            )
        return value


class ServerSettings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(env_prefix="SERVER_")

    host: str = "127.0.0.1"
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
    opsorchestra_allow_private_network: bool = False
    opsorchestra_http_max_retries: int = Field(default=2, ge=0, le=5)
    opsorchestra_http_retry_backoff_seconds: float = Field(default=0.25, ge=0.0, le=5.0)
    opsorchestra_auth_enabled: bool = False
    opsorchestra_jwt_public_key_path: str | None = None
    opsorchestra_jwks_url: str | None = None
    opsorchestra_jwks_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    opsorchestra_jwks_cache_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    opsorchestra_jwt_leeway_seconds: int = Field(default=30, ge=0, le=300)
    opsorchestra_jwt_issuer: str = "opsorchestra"
    opsorchestra_jwt_audience: str = "scalescore-api"
    opsorchestra_sub_claim: str = "sub"
    opsorchestra_tenant_claim: str = "tenant_id"
    opsorchestra_tenant_claim_fallbacks: list[str] = Field(
        default_factory=lambda: ["tenant", "tid"]
    )
    opsorchestra_email_claim: str = "email"
    opsorchestra_email_claim_fallbacks: list[str] = Field(
        default_factory=lambda: ["upn", "preferred_username"]
    )
    opsorchestra_roles_claim: str = "roles"
    opsorchestra_roles_claim_fallbacks: list[str] = Field(
        default_factory=lambda: ["groups", "scope", "scp"]
    )
    opsorchestra_require_email_claim: bool = True
    opsorchestra_require_roles_claim: bool = True
    external_oidc_auth_enabled: bool = False
    external_oidc_provider_name: str = "external-oidc"
    external_oidc_allow_private_network: bool = False
    external_oidc_jwt_public_key_path: str | None = None
    external_oidc_jwks_url: str | None = None
    external_oidc_jwks_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    external_oidc_jwks_cache_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    external_oidc_jwt_leeway_seconds: int = Field(default=30, ge=0, le=300)
    external_oidc_jwt_issuer: str = ""
    external_oidc_jwt_audience: str = "scalescore-api"
    external_oidc_sub_claim: str = "sub"
    external_oidc_tenant_claim: str = "tenant_id"
    external_oidc_tenant_claim_fallbacks: list[str] = Field(
        default_factory=lambda: ["tid", "tenant", "org_id"]
    )
    external_oidc_email_claim: str = "email"
    external_oidc_email_claim_fallbacks: list[str] = Field(
        default_factory=lambda: ["upn", "preferred_username"]
    )
    external_oidc_roles_claim: str = "roles"
    external_oidc_roles_claim_fallbacks: list[str] = Field(
        default_factory=lambda: ["groups", "scope", "scp"]
    )
    external_oidc_require_email_claim: bool = True
    external_oidc_require_roles_claim: bool = True
    opsorchestra_graph_export_url: str | None = None
    opsorchestra_graph_token: SecretStr | None = None
    opsorchestra_graph_timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    opsorchestra_graph_max_entities_per_type: int = Field(default=5000, ge=1, le=100_000)
    opsorchestra_outbound_url: str | None = None
    opsorchestra_outbound_token: SecretStr | None = None
    opsorchestra_outbound_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)


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
    async_assessment: AsyncAssessmentSettings = Field(default_factory=AsyncAssessmentSettings)

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

        if self.environment in {"staging", "production"}:
            ops_allow_private_network = self.integration.opsorchestra_allow_private_network
            if self.integration.opsorchestra_jwks_url:
                validate_remote_url(
                    self.integration.opsorchestra_jwks_url,
                    setting_name="INTEGRATION_OPSORCHESTRA_JWKS_URL",
                    require_https=True,
                    allow_private_network=ops_allow_private_network,
                )
            if self.integration.opsorchestra_graph_export_url:
                validate_remote_url(
                    self.integration.opsorchestra_graph_export_url,
                    setting_name="INTEGRATION_OPSORCHESTRA_GRAPH_EXPORT_URL",
                    require_https=True,
                    allow_private_network=ops_allow_private_network,
                )
            if self.integration.opsorchestra_outbound_url:
                validate_remote_url(
                    self.integration.opsorchestra_outbound_url,
                    setting_name="INTEGRATION_OPSORCHESTRA_OUTBOUND_URL",
                    require_https=True,
                    allow_private_network=ops_allow_private_network,
                )
            external_allow_private_network = self.integration.external_oidc_allow_private_network
            if self.integration.external_oidc_jwks_url:
                validate_remote_url(
                    self.integration.external_oidc_jwks_url,
                    setting_name="INTEGRATION_EXTERNAL_OIDC_JWKS_URL",
                    require_https=True,
                    allow_private_network=external_allow_private_network,
                )

        if self.integration.external_oidc_auth_enabled:
            if not (
                self.integration.external_oidc_jwt_public_key_path
                or self.integration.external_oidc_jwks_url
            ):
                raise ValueError(
                    "External OIDC auth requires INTEGRATION_EXTERNAL_OIDC_JWT_PUBLIC_KEY_PATH "
                    "or INTEGRATION_EXTERNAL_OIDC_JWKS_URL"
                )
            if not self.integration.external_oidc_jwt_issuer.strip():
                raise ValueError(
                    "INTEGRATION_EXTERNAL_OIDC_JWT_ISSUER is required when "
                    "INTEGRATION_EXTERNAL_OIDC_AUTH_ENABLED=true"
                )

        if (
            self.features.enable_async_assessments
            and self.async_assessment.mode == "broker"
            and not self.async_assessment.broker_url
        ):
            raise ValueError(
                "ASYNC_ASSESSMENT_BROKER_URL is required when ASYNC_ASSESSMENT_MODE=broker"
            )
        if (
            self.features.enable_async_assessments
            and self.environment in {"staging", "production"}
            and self.async_assessment.mode == "broker"
        ):
            broker_url = self.async_assessment.broker_url
            if broker_url and broker_url.startswith("redis://"):
                raise ValueError(
                    "ASYNC_ASSESSMENT_BROKER_URL must use rediss:// in staging/production"
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
