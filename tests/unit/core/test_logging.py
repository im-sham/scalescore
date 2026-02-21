"""Tests for logging and observability (ADR-0010)."""

from unittest.mock import patch


class TestSensitiveDataFiltering:
    """Test sensitive data is filtered from logs."""

    def test_password_is_redacted(self) -> None:
        from scalescore.core.logging import _recursive_filter

        data = {"username": "john", "password": "secret123"}
        result = _recursive_filter(data)

        assert result["username"] == "john"
        assert result["password"] == "[REDACTED]"

    def test_nested_secrets_are_redacted(self) -> None:
        from scalescore.core.logging import _recursive_filter

        data = {
            "user": {
                "email": "john@example.com",
                "api_key": "sk-12345",
            }
        }
        result = _recursive_filter(data)

        assert result["user"]["email"] == "john@example.com"
        assert result["user"]["api_key"] == "[REDACTED]"

    def test_list_values_are_filtered(self) -> None:
        from scalescore.core.logging import _recursive_filter

        data = {
            "users": [
                {"access_token": "abc", "name": "user1"},
                {"access_token": "def", "name": "user2"},
            ]
        }
        result = _recursive_filter(data)

        assert result["users"][0]["access_token"] == "[REDACTED]"
        assert result["users"][0]["name"] == "user1"
        assert result["users"][1]["access_token"] == "[REDACTED]"

    def test_various_sensitive_patterns(self) -> None:
        from scalescore.core.logging import _is_sensitive

        assert _is_sensitive("password") is True
        assert _is_sensitive("PASSWORD") is True
        assert _is_sensitive("user_password") is True
        assert _is_sensitive("api_key") is True
        assert _is_sensitive("apiKey") is True
        assert _is_sensitive("secret") is True
        assert _is_sensitive("jwt_token") is True
        assert _is_sensitive("authorization") is True
        assert _is_sensitive("credit_card") is True

        assert _is_sensitive("username") is False
        assert _is_sensitive("email") is False
        assert _is_sensitive("name") is False


class TestAuditLogging:
    """Test audit logging functionality."""

    def test_audit_event_types_exist(self) -> None:
        from scalescore.core.audit import AuditEventType

        assert AuditEventType.LOGIN_SUCCESS.value == "auth.login.success"
        assert AuditEventType.LOGIN_FAILURE.value == "auth.login.failure"
        assert AuditEventType.ACCESS_DENIED.value == "authz.access.denied"
        assert AuditEventType.ASSESSMENT_CREATED.value == "data.assessment.created"

    def test_audit_log_includes_required_fields(self) -> None:
        from scalescore.core.audit import AuditEventType, audit_log

        with patch("scalescore.core.audit._audit_logger") as mock_logger:
            audit_log(
                AuditEventType.LOGIN_SUCCESS,
                actor_id="user-123",
                tenant_id="tenant-456",
                ip_address="192.168.1.1",
            )

            mock_logger.info.assert_called_once()
            call_kwargs = mock_logger.info.call_args[1]

            assert call_kwargs["audit"] is True
            assert call_kwargs["actor_id"] == "user-123"
            assert call_kwargs["tenant_id"] == "tenant-456"
            assert call_kwargs["ip_address"] == "192.168.1.1"
            assert call_kwargs["success"] is True

    def test_audit_login_failure(self) -> None:
        from scalescore.core.audit import audit_login_failure

        with patch("scalescore.core.audit._audit_logger") as mock_logger:
            audit_login_failure(
                email="john@example.com",
                reason="invalid_password",
                ip_address="10.0.0.1",
            )

            call_kwargs = mock_logger.info.call_args[1]

            assert call_kwargs["success"] is False
            assert call_kwargs["details"]["email"] == "john@example.com"
            assert call_kwargs["details"]["reason"] == "invalid_password"


class TestCorrelationId:
    """Test correlation ID middleware."""

    def test_get_correlation_id_default(self) -> None:
        from scalescore.api.middleware import get_correlation_id

        assert get_correlation_id() == ""

    def test_correlation_id_context_var(self) -> None:
        from scalescore.api.middleware import correlation_id_ctx

        correlation_id_ctx.set("test-correlation-id")
        assert correlation_id_ctx.get() == "test-correlation-id"

        correlation_id_ctx.set("")


class TestLoggerFactory:
    """Test logger creation."""

    def test_get_logger_returns_bound_logger(self) -> None:
        from scalescore.core.logging import get_logger

        logger = get_logger("test.module")

        assert logger is not None
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_context_binding(self) -> None:
        import structlog

        from scalescore.core.logging import bind_context, clear_context, unbind_context

        clear_context()

        bind_context(user_id="user-123", request_id="req-456")

        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("user_id") == "user-123"
        assert ctx.get("request_id") == "req-456"

        unbind_context("user_id")
        ctx = structlog.contextvars.get_contextvars()
        assert "user_id" not in ctx

        clear_context()
