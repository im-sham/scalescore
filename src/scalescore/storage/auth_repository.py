from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from scalescore.config import settings
from scalescore.core.auth.roles import Role
from scalescore.core.exceptions import AuthenticationError, DatabaseError, ErrorCode

PASSWORD_HASH_ITERATIONS = 390_000
API_KEY_PREFIX = "ssk_"


@dataclass
class UserRecord:
    user_id: str
    tenant_id: str
    email: str
    roles: list[str]
    org_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


@dataclass
class APIKeyRecord:
    key_id: str
    user_id: str
    tenant_id: str
    name: str
    key_prefix: str
    roles: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass
class APIKeyPrincipal:
    key_id: str
    user_id: str
    tenant_id: str
    email: str
    roles: list[str]
    org_id: str | None
    expires_at: datetime | None


class SQLiteAuthRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._ensure_bootstrap_user()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS users (
                            user_id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            org_id TEXT,
                            email TEXT NOT NULL UNIQUE,
                            password_hash TEXT NOT NULL,
                            password_salt TEXT NOT NULL,
                            roles_json TEXT NOT NULL,
                            is_active INTEGER NOT NULL DEFAULT 1,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            last_login_at TEXT
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_users_tenant_email
                        ON users (tenant_id, email)
                        """
                    )
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS api_keys (
                            key_id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            tenant_id TEXT NOT NULL,
                            name TEXT NOT NULL,
                            key_prefix TEXT NOT NULL,
                            key_hash TEXT NOT NULL UNIQUE,
                            roles_json TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            expires_at TEXT,
                            last_used_at TEXT,
                            revoked_at TEXT,
                            FOREIGN KEY (user_id) REFERENCES users(user_id)
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_api_keys_user_created
                        ON api_keys (user_id, created_at DESC)
                        """
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to initialize auth storage", cause=err) from err

    def _hash_password(self, password: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PASSWORD_HASH_ITERATIONS,
        )
        return base64.b64encode(digest).decode("utf-8")

    def _new_password_material(self, password: str) -> tuple[str, str]:
        salt = secrets.token_bytes(16)
        return self._hash_password(password, salt), base64.b64encode(salt).decode("utf-8")

    def _verify_password(self, password: str, stored_hash: str, stored_salt: str) -> bool:
        salt = base64.b64decode(stored_salt.encode("utf-8"))
        candidate_hash = self._hash_password(password, salt)
        return hmac.compare_digest(candidate_hash, stored_hash)

    def _hash_api_key(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def _row_to_user(self, row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            org_id=row["org_id"],
            email=row["email"],
            roles=json.loads(row["roles_json"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_login_at=datetime.fromisoformat(row["last_login_at"])
            if row["last_login_at"]
            else None,
        )

    def _row_to_api_key(self, row: sqlite3.Row) -> APIKeyRecord:
        return APIKeyRecord(
            key_id=row["key_id"],
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            key_prefix=row["key_prefix"],
            roles=json.loads(row["roles_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            last_used_at=datetime.fromisoformat(row["last_used_at"])
            if row["last_used_at"]
            else None,
            revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
        )

    def get_user_by_email(self, email: str) -> UserRecord | None:
        normalized_email = email.strip().lower()
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT user_id, tenant_id, org_id, email, roles_json, is_active,
                           created_at, updated_at, last_login_at
                    FROM users
                    WHERE email = ?
                    """,
                    (normalized_email,),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load user by email", cause=err) from err
        if row is None:
            return None
        return self._row_to_user(row)

    def get_user(self, user_id: str) -> UserRecord | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT user_id, tenant_id, org_id, email, roles_json, is_active,
                           created_at, updated_at, last_login_at
                    FROM users
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load user", cause=err) from err
        if row is None:
            return None
        return self._row_to_user(row)

    def create_user(
        self,
        *,
        email: str,
        password: str,
        tenant_id: str,
        roles: list[str],
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> UserRecord:
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise AuthenticationError(
                message="Email is required",
                code=ErrorCode.INVALID_FIELD_VALUE,
            )
        if not password:
            raise AuthenticationError(
                message="Password is required",
                code=ErrorCode.INVALID_FIELD_VALUE,
            )
        now = datetime.now(UTC)
        db_user_id = user_id or f"user_{uuid4().hex[:12]}"
        password_hash, password_salt = self._new_password_material(password)

        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO users (
                            user_id,
                            tenant_id,
                            org_id,
                            email,
                            password_hash,
                            password_salt,
                            roles_json,
                            is_active,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            db_user_id,
                            tenant_id,
                            org_id,
                            normalized_email,
                            password_hash,
                            password_salt,
                            json.dumps(roles),
                            1,
                            now.isoformat(),
                            now.isoformat(),
                        ),
                    )
        except sqlite3.IntegrityError as err:
            raise AuthenticationError(
                message="A user with this email already exists",
                code=ErrorCode.DUPLICATE_ENTITY,
            ) from err
        except sqlite3.Error as err:
            raise DatabaseError("Failed to create user", cause=err) from err

        created = self.get_user(db_user_id)
        if created is None:
            raise DatabaseError("User creation failed unexpectedly")
        return created

    def authenticate_user(self, email: str, password: str) -> UserRecord | None:
        normalized_email = email.strip().lower()
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT user_id, tenant_id, org_id, email, roles_json, is_active,
                           created_at, updated_at, last_login_at, password_hash, password_salt
                    FROM users
                    WHERE email = ?
                    """,
                    (normalized_email,),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to authenticate user", cause=err) from err

        if row is None or not bool(row["is_active"]):
            return None

        if not self._verify_password(password, row["password_hash"], row["password_salt"]):
            return None

        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE users
                        SET last_login_at = ?, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (now, now, row["user_id"]),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to update user login timestamp", cause=err) from err

        refreshed = self.get_user(row["user_id"])
        if refreshed is None:
            raise DatabaseError("User record missing after authentication")
        return refreshed

    def create_api_key(
        self,
        *,
        user_id: str,
        tenant_id: str,
        name: str,
        roles: list[str],
        expires_in_days: int | None = 90,
    ) -> tuple[APIKeyRecord, str]:
        now = datetime.now(UTC)
        raw_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(36)}"
        key_hash = self._hash_api_key(raw_key)
        key_id = f"key_{uuid4().hex[:12]}"
        expires_at = now + timedelta(days=expires_in_days) if expires_in_days else None

        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO api_keys (
                            key_id,
                            user_id,
                            tenant_id,
                            name,
                            key_prefix,
                            key_hash,
                            roles_json,
                            created_at,
                            expires_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key_id,
                            user_id,
                            tenant_id,
                            name,
                            raw_key[:12],
                            key_hash,
                            json.dumps(roles),
                            now.isoformat(),
                            expires_at.isoformat() if expires_at else None,
                        ),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to create API key", cause=err) from err

        created = self.get_api_key(key_id)
        if created is None:
            raise DatabaseError("API key creation failed unexpectedly")
        return created, raw_key

    def get_api_key(self, key_id: str) -> APIKeyRecord | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT key_id, user_id, tenant_id, name, key_prefix, roles_json,
                           created_at, expires_at, last_used_at, revoked_at
                    FROM api_keys
                    WHERE key_id = ?
                    """,
                    (key_id,),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load API key", cause=err) from err
        if row is None:
            return None
        return self._row_to_api_key(row)

    def list_api_keys_for_user(self, user_id: str) -> list[APIKeyRecord]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT key_id, user_id, tenant_id, name, key_prefix, roles_json,
                           created_at, expires_at, last_used_at, revoked_at
                    FROM api_keys
                    WHERE user_id = ? AND revoked_at IS NULL
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                ).fetchall()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to list API keys", cause=err) from err

        return [self._row_to_api_key(row) for row in rows]

    def revoke_api_key(self, *, key_id: str, user_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    result = connection.execute(
                        """
                        UPDATE api_keys
                        SET revoked_at = ?
                        WHERE key_id = ? AND user_id = ? AND revoked_at IS NULL
                        """,
                        (now, key_id, user_id),
                    )
                    return result.rowcount > 0
        except sqlite3.Error as err:
            raise DatabaseError("Failed to revoke API key", cause=err) from err

    def authenticate_api_key(self, api_key: str) -> APIKeyPrincipal:
        key_hash = self._hash_api_key(api_key)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT
                        ak.key_id,
                        ak.user_id,
                        ak.tenant_id,
                        ak.roles_json AS key_roles_json,
                        ak.expires_at,
                        u.email,
                        u.org_id,
                        u.is_active
                    FROM api_keys ak
                    JOIN users u ON u.user_id = ak.user_id
                    WHERE ak.key_hash = ? AND ak.revoked_at IS NULL
                    """,
                    (key_hash,),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to authenticate API key", cause=err) from err

        if row is None or not bool(row["is_active"]):
            raise AuthenticationError(
                message="Invalid API key",
                code=ErrorCode.INVALID_API_KEY,
            )

        expires_at = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
        if expires_at and expires_at < datetime.now(UTC):
            self.revoke_api_key(key_id=row["key_id"], user_id=row["user_id"])
            raise AuthenticationError(
                message="API key has expired",
                code=ErrorCode.API_KEY_EXPIRED,
            )

        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
                        (now, row["key_id"]),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to update API key usage timestamp", cause=err) from err

        return APIKeyPrincipal(
            key_id=row["key_id"],
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            roles=json.loads(row["key_roles_json"]),
            org_id=row["org_id"],
            expires_at=expires_at,
        )

    def _ensure_bootstrap_user(self) -> None:
        if not (settings.is_development() or settings.is_testing()):
            return
        if self.get_user_by_email("dev@example.com") is not None:
            return

        try:
            self.create_user(
                user_id="dev-user-1",
                email="dev@example.com",
                password="dev",
                tenant_id="dev-tenant",
                org_id="org_1",
                roles=[Role.ADMIN.value],
            )
        except AuthenticationError:
            # Safe to ignore race/duplicate conditions during concurrent startup.
            pass


@lru_cache
def get_auth_repository() -> SQLiteAuthRepository:
    return SQLiteAuthRepository(settings.storage.effective_auth_db_path)
