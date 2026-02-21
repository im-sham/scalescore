from datetime import UTC, datetime

import pytest

from scalescore.core.auth.refresh import (
    InMemoryRefreshTokenRepository,
    RefreshTokenData,
    RefreshTokenService,
    SQLiteRefreshTokenRepository,
)
from scalescore.core.exceptions import AuthenticationError, ErrorCode


class TestRefreshTokenService:
    @pytest.fixture
    def service(self) -> RefreshTokenService:
        return RefreshTokenService()

    def test_create_refresh_token_returns_string(self, service: RefreshTokenService) -> None:
        token = service.create_refresh_token(
            user_id="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["analyst"],
        )
        assert isinstance(token, str)
        assert len(token) > 32

    def test_rotate_refresh_token_returns_new_tokens(self, service: RefreshTokenService) -> None:
        original_token = service.create_refresh_token(
            user_id="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["analyst"],
        )

        access_token, new_refresh = service.rotate_refresh_token(original_token)

        assert isinstance(access_token, str)
        assert isinstance(new_refresh, str)
        assert new_refresh != original_token

    def test_rotate_invalid_token_raises_error(self, service: RefreshTokenService) -> None:
        with pytest.raises(AuthenticationError) as exc_info:
            service.rotate_refresh_token("invalid-token")

        assert exc_info.value.code == ErrorCode.INVALID_REFRESH_TOKEN

    def test_reusing_token_revokes_all_sessions(self, service: RefreshTokenService) -> None:
        token = service.create_refresh_token(
            user_id="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["analyst"],
        )

        service.rotate_refresh_token(token)

        with pytest.raises(AuthenticationError) as exc_info:
            service.rotate_refresh_token(token)

        assert exc_info.value.code == ErrorCode.TOKEN_REUSE_DETECTED

    def test_revoke_token_prevents_use(self, service: RefreshTokenService) -> None:
        token = service.create_refresh_token(
            user_id="user-123",
            tenant_id="tenant-456",
            email="user@example.com",
            roles=["analyst"],
        )

        service.revoke_token(token)

        with pytest.raises(AuthenticationError) as exc_info:
            service.rotate_refresh_token(token)

        assert exc_info.value.code == ErrorCode.INVALID_REFRESH_TOKEN


class TestInMemoryRefreshTokenRepository:
    @pytest.fixture
    def repo(self) -> InMemoryRefreshTokenRepository:
        return InMemoryRefreshTokenRepository()

    def test_store_and_get(self, repo: InMemoryRefreshTokenRepository) -> None:
        token_data = RefreshTokenData(
            token_hash="abc123",
            user_id="user-1",
            tenant_id="tenant-1",
            email="user@test.com",
            roles=["viewer"],
            expires_at=datetime.now(UTC),
        )

        repo.store(token_data)
        result = repo.get("abc123")

        assert result is not None
        assert result.user_id == "user-1"

    def test_revoke_removes_token(self, repo: InMemoryRefreshTokenRepository) -> None:
        token_data = RefreshTokenData(
            token_hash="abc123",
            user_id="user-1",
            tenant_id="tenant-1",
            email="user@test.com",
            roles=["viewer"],
            expires_at=datetime.now(UTC),
        )

        repo.store(token_data)
        repo.revoke("abc123")

        assert repo.get("abc123") is None

    def test_revoke_all_for_user(self, repo: InMemoryRefreshTokenRepository) -> None:
        for i in range(3):
            repo.store(
                RefreshTokenData(
                    token_hash=f"token-{i}",
                    user_id="user-1",
                    tenant_id="tenant-1",
                    email="user@test.com",
                    roles=["viewer"],
                    expires_at=datetime.now(UTC),
                )
            )

        repo.revoke_all_for_user("user-1")

        for i in range(3):
            assert repo.get(f"token-{i}") is None


class TestSQLiteRefreshTokenRepository:
    def test_store_and_get_across_instances(self, tmp_path) -> None:
        db_path = tmp_path / "auth.sqlite3"
        repo_a = SQLiteRefreshTokenRepository(db_path)
        repo_b = SQLiteRefreshTokenRepository(db_path)

        token_data = RefreshTokenData(
            token_hash="abc123",
            user_id="user-1",
            tenant_id="tenant-1",
            email="user@test.com",
            roles=["viewer", "analyst"],
            expires_at=datetime.now(UTC),
        )

        repo_a.store(token_data)
        loaded = repo_b.get("abc123")

        assert loaded is not None
        assert loaded.user_id == "user-1"
        assert loaded.roles == ["viewer", "analyst"]
        assert loaded.used is False

    def test_mark_used_and_revoke(self, tmp_path) -> None:
        repo = SQLiteRefreshTokenRepository(tmp_path / "auth.sqlite3")
        token_data = RefreshTokenData(
            token_hash="abc123",
            user_id="user-1",
            tenant_id="tenant-1",
            email="user@test.com",
            roles=["viewer"],
            expires_at=datetime.now(UTC),
        )

        repo.store(token_data)
        repo.mark_used("abc123")
        loaded = repo.get("abc123")

        assert loaded is not None
        assert loaded.used is True

        repo.revoke("abc123")
        assert repo.get("abc123") is None
