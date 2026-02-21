# ADR-0009: Configuration Management

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore needs a robust configuration management strategy to support:
- Different environments (development, staging, production)
- Secure secrets handling (database credentials, API keys)
- Feature flags for gradual rollouts
- Runtime configuration without code changes
- Multi-tenant configuration where applicable

Currently, configuration is fragmented:
- `ScoringConfig` dataclass with hardcoded defaults in `scoring/engine.py`
- FastAPI app title/version hardcoded in `api/main.py`
- No environment-based configuration
- No secrets management pattern

This creates risks for deployment, security, and operational flexibility.

## Decision Drivers

- **Security-First**: Secrets must never be committed to code
- **Environment Parity**: Same code, different configs per environment
- **Fail-Fast**: Invalid configuration should fail at startup, not runtime
- **Observability**: Configuration should be loggable (without secrets)
- **Simplicity**: Minimize configuration complexity while meeting needs
- **Pydantic Alignment**: Leverage existing Pydantic v2 investment

## Considered Options

### Option 1: pydantic-settings with Environment Variables

Use pydantic-settings library for typed configuration from environment variables.

**Pros:**
- Native Pydantic v2 integration
- Type validation at startup
- Environment variable support built-in
- Dotenv file support for development
- Nested settings with prefixes
- Secret types with masking

**Cons:**
- Additional dependency (though minimal)
- Environment variables have limitations for complex structures

### Option 2: Python Config Files (settings.py)

Use Python modules for configuration with environment switching.

**Pros:**
- No dependencies
- Full Python expressiveness
- Easy to understand

**Cons:**
- Code and config coupled
- Harder to override at runtime
- Security risk (Python files can execute code)
- Not 12-factor app compliant

### Option 3: YAML/TOML Config Files

External configuration files loaded at startup.

**Pros:**
- Human-readable
- Supports complex nested structures
- Separate from code

**Cons:**
- No type validation without extra code
- File management across environments
- Secrets in files risk
- Additional parsing dependency

### Option 4: External Config Service (Consul, etcd)

Centralized configuration service with dynamic reloading.

**Pros:**
- Dynamic configuration updates
- Centralized management
- Feature flags support
- Audit logging

**Cons:**
- Infrastructure complexity
- Network dependency
- Overkill for current scale
- Operational overhead

## Decision

**Use Option 1: pydantic-settings with Environment Variables.**

We will:
1. Create a centralized `Settings` class using pydantic-settings
2. Use environment variables as the primary configuration source
3. Support `.env` files for development convenience
4. Define clear configuration hierarchy
5. Separate secrets from regular configuration
6. Validate all configuration at startup

Rationale:
- Aligns with existing Pydantic v2 usage
- 12-factor app compliant (environment-based)
- Type safety and validation built-in
- Industry standard for Python applications
- Simple to understand and operate

## Consequences

### Positive
- Typed, validated configuration throughout the application
- Clear separation of configuration from code
- Fail-fast on invalid configuration
- Secure secrets handling with masking
- Easy environment switching
- IDE support for configuration access

### Negative
- Requires environment variable management in deployment
- Complex configurations need flattening for env vars
- Additional dependency (pydantic-settings)

### Neutral
- Developers must manage `.env` files locally
- Deployment pipelines need env var configuration

## Implementation Notes

### Settings Class

```python
# src/scalescore/config.py
from functools import lru_cache
from pydantic import Field, SecretStr, field_validator
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
    echo: bool = False  # SQL logging
    
    @property
    def url(self) -> str:
        """Construct database URL (without password for logging)."""
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.name}"
    
    @property
    def url_with_password(self) -> str:
        """Construct full database URL with password."""
        password = self.password.get_secret_value()
        return f"postgresql://{self.user}:{password}@{self.host}:{self.port}/{self.name}"


class AuthSettings(BaseSettings):
    """Authentication configuration."""
    model_config = SettingsConfigDict(env_prefix="AUTH_")
    
    jwt_secret: SecretStr = Field(default=SecretStr("CHANGE_ME_IN_PRODUCTION"))
    jwt_algorithm: str = "RS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: SecretStr) -> SecretStr:
        if v.get_secret_value() == "CHANGE_ME_IN_PRODUCTION":
            import warnings
            warnings.warn(
                "Using default JWT secret. Set AUTH_JWT_SECRET in production!",
                UserWarning,
                stacklevel=2,
            )
        return v


class ScoringSettings(BaseSettings):
    """Scoring engine configuration."""
    model_config = SettingsConfigDict(env_prefix="SCORING_")
    
    base_score: float = Field(default=100.0, ge=0, le=100)
    critical_severity_weight: float = Field(default=25.0, ge=0)
    high_severity_weight: float = Field(default=15.0, ge=0)
    medium_severity_weight: float = Field(default=8.0, ge=0)
    low_severity_weight: float = Field(default=3.0, ge=0)
    bottleneck_threshold: float = Field(default=0.8, ge=0, le=1)


class FeatureFlags(BaseSettings):
    """Feature flag configuration."""
    model_config = SettingsConfigDict(env_prefix="FEATURE_")
    
    enable_recommendations: bool = True
    enable_bottleneck_detection: bool = True
    enable_dependency_graph: bool = True
    enable_multi_tenant: bool = False  # Disabled until auth implemented
    enable_async_assessments: bool = False  # Disabled until background jobs


class Settings(BaseSettings):
    """Main application settings."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )
    
    # Application
    app_name: str = "ScaleScore"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", pattern=r"^(development|staging|production)$")
    debug: bool = False
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = Field(default=1, ge=1)
    
    # Logging
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_format: str = "json"  # json or text
    
    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    
    @field_validator("debug")
    @classmethod
    def validate_debug(cls, v: bool, info) -> bool:
        env = info.data.get("environment", "development")
        if v and env == "production":
            raise ValueError("Debug mode cannot be enabled in production")
        return v
    
    def is_production(self) -> bool:
        return self.environment == "production"
    
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience accessor
settings = get_settings()
```

### Environment Variables

```bash
# .env.example (commit this, not .env)

# Application
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=scalescore
DB_USER=scalescore
DB_PASSWORD=your_password_here
DB_POOL_SIZE=5

# Authentication
AUTH_JWT_SECRET=your_jwt_secret_here
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=30

# Scoring
SCORING_BASE_SCORE=100.0
SCORING_CRITICAL_SEVERITY_WEIGHT=25.0

# Feature Flags
FEATURE_ENABLE_MULTI_TENANT=false
FEATURE_ENABLE_ASYNC_ASSESSMENTS=false
```

### Usage in Application

```python
# src/scalescore/api/main.py
from fastapi import FastAPI
from scalescore.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
)

@app.on_event("startup")
async def startup():
    # Log configuration (secrets automatically masked)
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        "Starting application",
        extra={
            "environment": settings.environment,
            "database_url": settings.database.url,  # Password not included
            "features": settings.features.model_dump(),
        },
    )
```

### Using Settings in Scoring Engine

```python
# src/scalescore/scoring/engine.py
from scalescore.config import settings

class ScoringEngine:
    def __init__(self, config: ScoringSettings | None = None):
        self.config = config or settings.scoring
    
    def calculate_penalty(self, severity: str) -> float:
        weights = {
            "critical": self.config.critical_severity_weight,
            "high": self.config.high_severity_weight,
            "medium": self.config.medium_severity_weight,
            "low": self.config.low_severity_weight,
        }
        return weights.get(severity, 0)
```

### Dependency Injection Pattern

```python
# src/scalescore/api/dependencies.py
from fastapi import Depends
from functools import lru_cache
from scalescore.config import Settings, get_settings


def get_scoring_settings(settings: Settings = Depends(get_settings)):
    return settings.scoring


def get_feature_flags(settings: Settings = Depends(get_settings)):
    return settings.features
```

### Configuration Validation at Startup

```python
# src/scalescore/main.py
import sys
from pydantic import ValidationError
from scalescore.config import Settings


def validate_configuration() -> Settings:
    """Validate configuration at startup."""
    try:
        settings = Settings()
        
        # Production-specific validations
        if settings.is_production():
            if settings.auth.jwt_secret.get_secret_value() == "CHANGE_ME_IN_PRODUCTION":
                raise ValueError("JWT secret must be set in production")
            if not settings.database.password.get_secret_value():
                raise ValueError("Database password must be set in production")
        
        return settings
    except ValidationError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    settings = validate_configuration()
    # Start application
```

### Configuration Hierarchy

```
┌─────────────────────────────────────────────────────────────────────┐
│                   Configuration Hierarchy (Priority)                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. Environment Variables (highest priority)                        │
│     └── SCALESCORE_ENVIRONMENT=production                           │
│                                                                      │
│  2. .env File                                                        │
│     └── ENVIRONMENT=staging                                          │
│                                                                      │
│  3. Default Values in Settings class (lowest priority)              │
│     └── environment: str = "development"                             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Gitignore Configuration

```gitignore
# .gitignore

# Environment files with secrets
.env
.env.local
.env.*.local

# Keep example
!.env.example
```

## Related Decisions

- ADR-0001: Pydantic v2 for Models (pydantic-settings alignment)
- ADR-0006: PostgreSQL as Primary Database (database configuration)
- ADR-0010: Structured Logging and Observability (log configuration)
- ADR-0011: Authentication Strategy (auth configuration)

## Notes

- Add `pydantic-settings>=2.0` to project dependencies
- Create `.env.example` with all configuration options documented
- Document required environment variables in deployment runbook
- Consider adding configuration validation to CI/CD pipeline
- For production, use secrets managers (AWS Secrets Manager, HashiCorp Vault) and inject as environment variables
