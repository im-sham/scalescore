"""Tests for configuration management (ADR-0009)."""

import os
from unittest.mock import patch

import pytest


class TestSettings:
    """Test the Settings class."""

    def test_default_settings_load(self) -> None:
        """Verify default settings load without .env file."""
        from scalescore.config import Settings

        settings = Settings()

        assert settings.app_name == "ScaleScore"
        assert settings.app_version == "0.1.0"
        assert settings.environment == "development"
        assert settings.debug is False
        assert settings.integration.opsorchestra_auth_enabled is False
        assert settings.integration.opsorchestra_jwks_url is None
        assert settings.integration.opsorchestra_require_email_claim is True
        assert settings.integration.opsorchestra_require_roles_claim is True
        assert settings.integration.external_oidc_auth_enabled is False
        assert settings.integration.external_oidc_jwks_url is None
        assert settings.integration.external_oidc_require_email_claim is True
        assert settings.integration.external_oidc_require_roles_claim is True
        assert settings.auth.login_rate_limit_requests == 120
        assert settings.integration.opsorchestra_http_max_retries == 2
        assert settings.async_assessment.mode == "poll"
        assert settings.async_assessment.max_outstanding_jobs_per_tenant == 25
        assert settings.async_assessment.scheduled_dispatch_poll_interval_seconds == 30.0

    def test_environment_validation(self) -> None:
        """Verify environment must be valid value."""
        from scalescore.config import Settings

        with pytest.raises(ValueError):
            Settings(environment="invalid")

    def test_production_requires_jwt_secret(self) -> None:
        """Verify production mode requires JWT secret to be changed."""
        from scalescore.config import Settings

        with pytest.raises(ValueError, match="JWT secret must be set"):
            Settings(environment="production")

    def test_production_rejects_debug_mode(self) -> None:
        """Verify debug mode cannot be enabled in production."""
        from scalescore.config import Settings

        with pytest.raises(ValueError, match="Debug mode cannot be enabled"):
            Settings(
                environment="production",
                debug=True,
                auth__jwt_secret="real-secret-here",
            )

    def test_production_rejects_skip_auth(self) -> None:
        """Verify auth skip cannot be enabled in production."""
        from pydantic import SecretStr

        from scalescore.config import AuthSettings, Settings

        with pytest.raises(ValueError, match="Authentication cannot be skipped"):
            Settings(
                environment="production",
                auth=AuthSettings(
                    jwt_secret=SecretStr("real-secret-here"),
                    skip_auth=True,
                ),
            )

    def test_database_url_construction(self) -> None:
        """Verify database URLs are constructed correctly."""
        from scalescore.config import DatabaseSettings

        db = DatabaseSettings(
            host="myhost",
            port=5432,
            name="mydb",
            user="myuser",
            password="mypass",
        )

        assert db.url == "postgresql://myuser@myhost:5432/mydb"
        assert db.get_url_with_password() == "postgresql://myuser:mypass@myhost:5432/mydb"

    def test_environment_override(self) -> None:
        """Verify environment variables override defaults."""
        from scalescore.config import Settings

        with patch.dict(os.environ, {"ENVIRONMENT": "staging", "LOG_LEVEL": "WARNING"}):
            settings = Settings()

            assert settings.environment == "staging"
            assert settings.log_level == "WARNING"

    def test_nested_settings_override(self) -> None:
        """Verify nested settings can be overridden."""
        from scalescore.config import Settings

        with patch.dict(os.environ, {"DB_HOST": "remotehost", "DB_PORT": "5433"}):
            settings = Settings()

            assert settings.database.host == "remotehost"
            assert settings.database.port == 5433

    def test_staging_rejects_non_https_opsorchestra_urls(self) -> None:
        """Verify staging requires HTTPS for remote OpsOrchestra endpoints."""
        from scalescore.config import IntegrationSettings, Settings

        with pytest.raises(ValueError, match="must use https"):
            Settings(
                environment="staging",
                integration=IntegrationSettings(
                    opsorchestra_jwks_url="http://opsorchestra.example/jwks"
                ),
            )

    def test_staging_rejects_non_https_external_oidc_jwks_url(self) -> None:
        """Verify staging requires HTTPS for external OIDC JWKS URLs."""
        from scalescore.config import IntegrationSettings, Settings

        with pytest.raises(ValueError, match="must use https"):
            Settings(
                environment="staging",
                integration=IntegrationSettings(
                    external_oidc_jwks_url="http://idp.example/jwks"
                ),
            )

    def test_external_oidc_enabled_requires_issuer(self) -> None:
        from scalescore.config import IntegrationSettings, Settings

        with pytest.raises(ValueError, match="INTEGRATION_EXTERNAL_OIDC_JWT_ISSUER"):
            Settings(
                integration=IntegrationSettings(
                    external_oidc_auth_enabled=True,
                    external_oidc_jwt_public_key_path="/tmp/idp.pem",
                    external_oidc_jwt_issuer="",
                ),
            )

    def test_external_oidc_enabled_requires_key_or_jwks(self) -> None:
        from scalescore.config import IntegrationSettings, Settings

        with pytest.raises(ValueError, match="External OIDC auth requires"):
            Settings(
                integration=IntegrationSettings(
                    external_oidc_auth_enabled=True,
                    external_oidc_jwt_issuer="https://idp.example.com/",
                    external_oidc_jwt_public_key_path=None,
                    external_oidc_jwks_url=None,
                ),
            )

    def test_is_environment_helpers(self) -> None:
        """Verify environment helper methods work correctly."""
        from pydantic import SecretStr

        from scalescore.config import AuthSettings, Settings

        dev = Settings(environment="development")
        assert dev.is_development() is True
        assert dev.is_production() is False
        assert dev.is_testing() is False

        prod = Settings(
            environment="production",
            auth=AuthSettings(jwt_secret=SecretStr("real-secret")),
        )
        assert prod.is_production() is True
        assert prod.is_development() is False

        test = Settings(environment="testing")
        assert test.is_testing() is True

    def test_broker_mode_requires_broker_url(self) -> None:
        from scalescore.config import AsyncAssessmentSettings, FeatureFlags, Settings

        with pytest.raises(ValueError, match="ASYNC_ASSESSMENT_BROKER_URL is required"):
            Settings(
                features=FeatureFlags(enable_async_assessments=True),
                async_assessment=AsyncAssessmentSettings(mode="broker"),
            )

    def test_staging_broker_mode_requires_tls_redis(self) -> None:
        from scalescore.config import AsyncAssessmentSettings, FeatureFlags, Settings

        with pytest.raises(ValueError, match="must use rediss://"):
            Settings(
                environment="staging",
                features=FeatureFlags(enable_async_assessments=True),
                async_assessment=AsyncAssessmentSettings(
                    mode="broker",
                    broker_url="redis://redis.internal:6379/0",
                ),
            )


class TestScoringConfig:
    """Test ScoringConfig integration with settings."""

    def test_from_settings(self) -> None:
        """Verify ScoringConfig.from_settings() works."""
        from scalescore.scoring.engine import ScoringConfig

        config = ScoringConfig.from_settings()

        assert config.base_score == 100.0
        assert config.assessment_version == "1.0"

    def test_custom_config_override(self) -> None:
        """Verify custom config values can override defaults."""
        from scalescore.scoring.engine import ScoringConfig

        config = ScoringConfig(base_score=80.0)

        assert config.base_score == 80.0


class TestFeatureFlags:
    """Test feature flag configuration."""

    def test_default_feature_flags(self) -> None:
        """Verify default feature flag values."""
        from scalescore.config import Settings

        settings = Settings()

        assert settings.features.enable_recommendations is True
        assert settings.features.enable_bottleneck_detection is True
        assert settings.features.enable_multi_tenant is False
        assert settings.features.enable_async_assessments is False

    def test_feature_flag_override(self) -> None:
        """Verify feature flags can be overridden."""
        from scalescore.config import Settings

        with patch.dict(os.environ, {"FEATURE_ENABLE_MULTI_TENANT": "true"}):
            settings = Settings()

            assert settings.features.enable_multi_tenant is True
