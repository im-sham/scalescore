from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel

from scalescore.config import settings
from scalescore.core.exceptions import AuthenticationError, ErrorCode


class TokenPayload(BaseModel):
    sub: str
    tenant_id: str
    email: str
    roles: list[str]
    exp: datetime
    iat: datetime


class JWTService:
    def __init__(self) -> None:
        self._private_key: rsa.RSAPrivateKey | None = None
        self._public_key: rsa.RSAPublicKey | None = None
        self._init_keys()

    def _init_keys(self) -> None:
        self._private_key = self._load_private_key()
        self._public_key = self._load_public_key()

    def _load_private_key(self) -> rsa.RSAPrivateKey | None:
        key_path = settings.auth.jwt_private_key_path
        if key_path:
            with open(key_path, "rb") as f:
                return serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                )  # type: ignore[return-value]

        if settings.is_development() or settings.is_testing():
            return rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )

        raise ValueError("JWT private key not configured for production")

    def _load_public_key(self) -> rsa.RSAPublicKey | None:
        key_path = settings.auth.jwt_public_key_path
        if key_path:
            with open(key_path, "rb") as f:
                return serialization.load_pem_public_key(f.read())  # type: ignore[return-value]

        if self._private_key:
            return self._private_key.public_key()

        return None

    def create_access_token(
        self,
        user_id: str,
        tenant_id: str,
        email: str,
        roles: list[str],
    ) -> str:
        if not self._private_key:
            raise ValueError("Private key not available for signing")

        now = datetime.now(UTC)
        expires = now + timedelta(minutes=settings.auth.access_token_expire_minutes)

        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "roles": roles,
            "iat": now,
            "exp": expires,
            "iss": "scalescore",
            "aud": "scalescore-api",
        }

        return jwt.encode(
            payload,
            self._private_key,
            algorithm="RS256",
        )

    def verify_token(self, token: str) -> TokenPayload:
        if not self._public_key:
            raise ValueError("Public key not available for verification")

        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                audience="scalescore-api",
                issuer="scalescore",
            )
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError as err:
            raise AuthenticationError(
                message="Token has expired",
                code=ErrorCode.TOKEN_EXPIRED,
            ) from err
        except jwt.InvalidTokenError as err:
            raise AuthenticationError(
                message="Invalid token",
                code=ErrorCode.INVALID_TOKEN,
                details={"reason": str(err)},
            ) from err

    def get_public_key_jwk(self) -> dict[str, Any]:
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": "scalescore-key-1",
        }
