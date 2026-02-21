from datetime import UTC, datetime, timedelta

import pytest

from scalescore.core.auth.jwt import JWTService, TokenPayload
from scalescore.core.exceptions import AuthenticationError, ErrorCode


class TestJWTService:
    @pytest.fixture
    def jwt_service(self) -> JWTService:
        return JWTService()

    def test_create_access_token_returns_string(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["analyst"],
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_token_returns_payload(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["analyst", "viewer"],
        )

        payload = jwt_service.verify_token(token)

        assert isinstance(payload, TokenPayload)
        assert payload.sub == "user-123"
        assert payload.tenant_id == "tenant-456"
        assert payload.email == "user@example.com"
        assert payload.roles == ["analyst", "viewer"]

    def test_verify_invalid_token_raises_error(self, jwt_service: JWTService) -> None:
        with pytest.raises(AuthenticationError) as exc_info:
            jwt_service.verify_token("invalid.token.here")

        assert exc_info.value.code == ErrorCode.INVALID_TOKEN

    def test_verify_tampered_token_raises_error(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["analyst"],
        )
        tampered = token[:-5] + "XXXXX"

        with pytest.raises(AuthenticationError) as exc_info:
            jwt_service.verify_token(tampered)

        assert exc_info.value.code == ErrorCode.INVALID_TOKEN

    def test_token_contains_expected_claims(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["admin"],
        )

        payload = jwt_service.verify_token(token)

        assert payload.iat is not None
        assert payload.exp is not None
        assert payload.exp > payload.iat


class TestTokenPayload:
    def test_token_payload_model(self) -> None:
        now = datetime.now(UTC)
        payload = TokenPayload(
            sub="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["analyst"],
            exp=now + timedelta(hours=1),
            iat=now,
        )

        assert payload.sub == "user-123"
        assert payload.tenant_id == "tenant-456"
        assert payload.roles == ["analyst"]
