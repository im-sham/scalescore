from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from scalescore.config import settings
from scalescore.core.auth.jwt import TokenPayload
from scalescore.core.exceptions import AuthenticationError, ErrorCode


class OpsOrchestraAuthService:
    """Validate and map OpsOrchestra-issued JWTs into ScaleScore token payloads."""

    def __init__(
        self,
        *,
        public_key_path: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        sub_claim: str | None = None,
        tenant_claim: str | None = None,
        email_claim: str | None = None,
        roles_claim: str | None = None,
    ) -> None:
        integration = settings.integration
        self._public_key_path = public_key_path or integration.opsorchestra_jwt_public_key_path
        self._issuer = issuer or integration.opsorchestra_jwt_issuer
        self._audience = audience or integration.opsorchestra_jwt_audience
        self._sub_claim = sub_claim or integration.opsorchestra_sub_claim
        self._tenant_claim = tenant_claim or integration.opsorchestra_tenant_claim
        self._email_claim = email_claim or integration.opsorchestra_email_claim
        self._roles_claim = roles_claim or integration.opsorchestra_roles_claim
        self._public_key = self._load_public_key()

    def _load_public_key(self) -> rsa.RSAPublicKey:
        if not self._public_key_path:
            raise ValueError("OpsOrchestra JWT public key path is not configured")
        with open(Path(self._public_key_path), "rb") as handle:
            loaded_key = serialization.load_pem_public_key(handle.read())
        if not isinstance(loaded_key, rsa.RSAPublicKey):
            raise ValueError("OpsOrchestra JWT public key must be an RSA public key")
        return loaded_key

    @staticmethod
    def _as_datetime(value: Any, claim_name: str) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        raise AuthenticationError(
            message=f"Missing or invalid '{claim_name}' claim",
            code=ErrorCode.INVALID_TOKEN,
        )

    @staticmethod
    def _as_roles(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(role).strip() for role in value if str(role).strip()]
        if isinstance(value, str):
            if "," in value:
                return [part.strip() for part in value.split(",") if part.strip()]
            return [value] if value.strip() else []
        return []

    def verify_parent_token(self, token: str) -> TokenPayload:
        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
            )
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

        sub = claims.get(self._sub_claim)
        tenant_id = claims.get(self._tenant_claim)
        if not sub:
            raise AuthenticationError(
                message=f"Missing required claim: {self._sub_claim}",
                code=ErrorCode.INVALID_TOKEN,
            )
        if not tenant_id:
            raise AuthenticationError(
                message=f"Missing required claim: {self._tenant_claim}",
                code=ErrorCode.INVALID_TOKEN,
            )

        email = claims.get(self._email_claim) or f"{sub}@opsorchestra.local"
        roles = self._as_roles(claims.get(self._roles_claim, []))
        if not roles:
            roles = ["viewer"]

        try:
            return TokenPayload(
                sub=str(sub),
                tenant_id=str(tenant_id),
                email=str(email),
                roles=roles,
                exp=self._as_datetime(claims.get("exp"), "exp"),
                iat=self._as_datetime(claims.get("iat"), "iat"),
            )
        except ValidationError as err:
            raise AuthenticationError(
                message="Invalid token payload",
                code=ErrorCode.INVALID_TOKEN,
                details={"reason": str(err)},
            ) from err


@lru_cache
def get_opsorchestra_auth_service() -> OpsOrchestraAuthService:
    return OpsOrchestraAuthService()
