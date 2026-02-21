from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from scalescore.config import settings
from scalescore.core.auth.jwt import JWTService
from scalescore.core.exceptions import AuthenticationError, DatabaseError, ErrorCode


@dataclass
class RefreshTokenData:
    token_hash: str
    user_id: str
    tenant_id: str
    email: str
    roles: list[str]
    expires_at: datetime
    used: bool = False
    device_info: str | None = None


class RefreshTokenRepository(Protocol):
    def store(self, token_data: RefreshTokenData) -> None: ...
    def get(self, token_hash: str) -> RefreshTokenData | None: ...
    def mark_used(self, token_hash: str) -> None: ...
    def revoke(self, token_hash: str) -> None: ...
    def revoke_all_for_user(self, user_id: str) -> None: ...


class InMemoryRefreshTokenRepository:
    def __init__(self) -> None:
        self._tokens: dict[str, RefreshTokenData] = {}

    def store(self, token_data: RefreshTokenData) -> None:
        self._tokens[token_data.token_hash] = token_data

    def get(self, token_hash: str) -> RefreshTokenData | None:
        return self._tokens.get(token_hash)

    def mark_used(self, token_hash: str) -> None:
        if token_hash in self._tokens:
            self._tokens[token_hash].used = True

    def revoke(self, token_hash: str) -> None:
        self._tokens.pop(token_hash, None)

    def revoke_all_for_user(self, user_id: str) -> None:
        to_remove = [h for h, t in self._tokens.items() if t.user_id == user_id]
        for token_hash in to_remove:
            del self._tokens[token_hash]


class SQLiteRefreshTokenRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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
                        CREATE TABLE IF NOT EXISTS refresh_tokens (
                            token_hash TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            tenant_id TEXT NOT NULL,
                            email TEXT NOT NULL,
                            roles_json TEXT NOT NULL,
                            expires_at TEXT NOT NULL,
                            used INTEGER NOT NULL DEFAULT 0,
                            device_info TEXT,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user
                        ON refresh_tokens (user_id)
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_tenant
                        ON refresh_tokens (tenant_id)
                        """
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to initialize refresh token storage", cause=err) from err

    def store(self, token_data: RefreshTokenData) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO refresh_tokens (
                            token_hash,
                            user_id,
                            tenant_id,
                            email,
                            roles_json,
                            expires_at,
                            used,
                            device_info
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            token_data.token_hash,
                            token_data.user_id,
                            token_data.tenant_id,
                            token_data.email,
                            json.dumps(token_data.roles),
                            token_data.expires_at.isoformat(),
                            int(token_data.used),
                            token_data.device_info,
                        ),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to persist refresh token", cause=err) from err

    def get(self, token_hash: str) -> RefreshTokenData | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT token_hash, user_id, tenant_id, email, roles_json, expires_at, used, device_info
                    FROM refresh_tokens
                    WHERE token_hash = ?
                    """,
                    (token_hash,),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load refresh token", cause=err) from err

        if row is None:
            return None

        return RefreshTokenData(
            token_hash=row["token_hash"],
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            roles=json.loads(row["roles_json"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            used=bool(row["used"]),
            device_info=row["device_info"],
        )

    def mark_used(self, token_hash: str) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        "UPDATE refresh_tokens SET used = 1 WHERE token_hash = ?",
                        (token_hash,),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to mark refresh token as used", cause=err) from err

    def revoke(self, token_hash: str) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        "DELETE FROM refresh_tokens WHERE token_hash = ?",
                        (token_hash,),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to revoke refresh token", cause=err) from err

    def revoke_all_for_user(self, user_id: str) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        "DELETE FROM refresh_tokens WHERE user_id = ?",
                        (user_id,),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to revoke user refresh tokens", cause=err) from err


class RefreshTokenService:
    def __init__(
        self,
        repository: RefreshTokenRepository | None = None,
        jwt_service: JWTService | None = None,
    ) -> None:
        self.repository = repository or InMemoryRefreshTokenRepository()
        self.jwt_service = jwt_service or JWTService()
        self.token_length = 64
        self.expire_days = settings.auth.refresh_token_expire_days

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_refresh_token(
        self,
        user_id: str,
        tenant_id: str,
        email: str,
        roles: list[str],
        device_info: str | None = None,
    ) -> str:
        token = secrets.token_urlsafe(self.token_length)
        expires_at = datetime.now(UTC) + timedelta(days=self.expire_days)

        token_data = RefreshTokenData(
            token_hash=self._hash_token(token),
            user_id=user_id,
            tenant_id=tenant_id,
            email=email,
            roles=roles,
            expires_at=expires_at,
            device_info=device_info,
        )
        self.repository.store(token_data)

        return token

    def rotate_refresh_token(
        self,
        old_token: str,
        device_info: str | None = None,
    ) -> tuple[str, str]:
        old_hash = self._hash_token(old_token)

        token_data = self.repository.get(old_hash)
        if not token_data:
            raise AuthenticationError(
                message="Invalid refresh token",
                code=ErrorCode.INVALID_REFRESH_TOKEN,
            )

        if token_data.expires_at < datetime.now(UTC):
            self.repository.revoke(old_hash)
            raise AuthenticationError(
                message="Refresh token has expired",
                code=ErrorCode.REFRESH_TOKEN_EXPIRED,
            )

        if token_data.used:
            self.repository.revoke_all_for_user(token_data.user_id)
            raise AuthenticationError(
                message="Token reuse detected - all sessions revoked",
                code=ErrorCode.TOKEN_REUSE_DETECTED,
            )

        self.repository.mark_used(old_hash)

        new_refresh_token = self.create_refresh_token(
            user_id=token_data.user_id,
            tenant_id=token_data.tenant_id,
            email=token_data.email,
            roles=token_data.roles,
            device_info=device_info,
        )

        new_access_token = self.jwt_service.create_access_token(
            user_id=token_data.user_id,
            tenant_id=token_data.tenant_id,
            email=token_data.email,
            roles=token_data.roles,
        )

        return new_access_token, new_refresh_token

    def revoke_token(self, token: str) -> None:
        token_hash = self._hash_token(token)
        self.repository.revoke(token_hash)


@lru_cache
def get_sqlite_refresh_token_repository() -> SQLiteRefreshTokenRepository:
    return SQLiteRefreshTokenRepository(settings.storage.refresh_tokens_db_path)
