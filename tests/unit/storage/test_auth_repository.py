from datetime import UTC, datetime, timedelta

import pytest

from scalescore.core.exceptions import AuthenticationError, ErrorCode
from scalescore.storage.auth_repository import SQLiteAuthRepository


def test_create_and_authenticate_user(tmp_path) -> None:
    repository = SQLiteAuthRepository(tmp_path / "auth.sqlite3")
    created = repository.create_user(
        email="new.user@example.com",
        password="super-secret",
        tenant_id="tenant_a",
        org_id="org_a",
        roles=["analyst"],
    )

    assert created.email == "new.user@example.com"
    assert created.tenant_id == "tenant_a"
    assert created.org_id == "org_a"
    assert created.roles == ["analyst"]

    authenticated = repository.authenticate_user(
        email="new.user@example.com",
        password="super-secret",
    )
    assert authenticated is not None
    assert authenticated.user_id == created.user_id
    assert authenticated.last_login_at is not None


def test_duplicate_user_email_is_rejected(tmp_path) -> None:
    repository = SQLiteAuthRepository(tmp_path / "auth.sqlite3")
    repository.create_user(
        email="duplicate@example.com",
        password="password-1",
        tenant_id="tenant_a",
        org_id="org_a",
        roles=["analyst"],
    )

    with pytest.raises(AuthenticationError) as exc_info:
        repository.create_user(
            email="duplicate@example.com",
            password="password-2",
            tenant_id="tenant_a",
            org_id="org_a",
            roles=["viewer"],
        )

    assert exc_info.value.code == ErrorCode.DUPLICATE_ENTITY


def test_api_key_create_authenticate_and_revoke(tmp_path) -> None:
    repository = SQLiteAuthRepository(tmp_path / "auth.sqlite3")
    user = repository.create_user(
        email="apikey.user@example.com",
        password="super-secret",
        tenant_id="tenant_a",
        org_id="org_a",
        roles=["admin"],
    )

    key_record, raw_key = repository.create_api_key(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        name="ci-bot",
        roles=["viewer"],
        expires_in_days=30,
    )

    principal = repository.authenticate_api_key(raw_key)
    assert principal.user_id == user.user_id
    assert principal.tenant_id == user.tenant_id
    assert principal.roles == ["viewer"]
    assert principal.key_id == key_record.key_id

    revoked = repository.revoke_api_key(key_id=key_record.key_id, user_id=user.user_id)
    assert revoked is True

    with pytest.raises(AuthenticationError) as exc_info:
        repository.authenticate_api_key(raw_key)
    assert exc_info.value.code == ErrorCode.INVALID_API_KEY


def test_expired_api_key_is_rejected(tmp_path) -> None:
    repository = SQLiteAuthRepository(tmp_path / "auth.sqlite3")
    user = repository.create_user(
        email="expired.key@example.com",
        password="super-secret",
        tenant_id="tenant_a",
        org_id="org_a",
        roles=["admin"],
    )

    key_record, raw_key = repository.create_api_key(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        name="short-lived",
        roles=["viewer"],
        expires_in_days=1,
    )

    # Force expiry for deterministic test behavior.
    with repository._connect() as connection:  # noqa: SLF001
        with connection:
            connection.execute(
                "UPDATE api_keys SET expires_at = ? WHERE key_id = ?",
                ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), key_record.key_id),
            )

    with pytest.raises(AuthenticationError) as exc_info:
        repository.authenticate_api_key(raw_key)
    assert exc_info.value.code == ErrorCode.API_KEY_EXPIRED
