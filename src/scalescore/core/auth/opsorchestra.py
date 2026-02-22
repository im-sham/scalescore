from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError

from scalescore.config import settings
from scalescore.core.auth.jwt import TokenPayload
from scalescore.core.exceptions import AuthenticationError, ErrorCode, ScaleScoreError
from scalescore.core.logging import get_logger
from scalescore.core.network import validate_remote_url

logger = get_logger(__name__)


class OpsOrchestraAuthService:
    """Validate and map OpsOrchestra-issued JWTs into ScaleScore token payloads."""

    def __init__(
        self,
        *,
        public_key_path: str | None = None,
        jwks_url: str | None = None,
        jwks_timeout_seconds: float | None = None,
        jwks_cache_ttl_seconds: int | None = None,
        jwt_leeway_seconds: int | None = None,
        tenant_claim_fallbacks: list[str] | None = None,
        email_claim_fallbacks: list[str] | None = None,
        roles_claim_fallbacks: list[str] | None = None,
        allow_private_network: bool | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        sub_claim: str | None = None,
        tenant_claim: str | None = None,
        email_claim: str | None = None,
        roles_claim: str | None = None,
        require_email_claim: bool | None = None,
        require_roles_claim: bool | None = None,
    ) -> None:
        integration = settings.integration
        self._public_key_path = public_key_path or integration.opsorchestra_jwt_public_key_path
        self._jwks_url = jwks_url or integration.opsorchestra_jwks_url
        self._jwks_timeout_seconds = (
            jwks_timeout_seconds
            if jwks_timeout_seconds is not None
            else integration.opsorchestra_jwks_timeout_seconds
        )
        self._jwks_cache_ttl_seconds = (
            jwks_cache_ttl_seconds
            if jwks_cache_ttl_seconds is not None
            else integration.opsorchestra_jwks_cache_ttl_seconds
        )
        self._jwt_leeway_seconds = (
            jwt_leeway_seconds
            if jwt_leeway_seconds is not None
            else integration.opsorchestra_jwt_leeway_seconds
        )
        self._allow_private_network = (
            allow_private_network
            if allow_private_network is not None
            else integration.opsorchestra_allow_private_network
        )
        self._require_https = not (settings.is_development() or settings.is_testing())
        self._max_retries = integration.opsorchestra_http_max_retries
        self._retry_backoff_seconds = integration.opsorchestra_http_retry_backoff_seconds
        self._issuer = issuer or integration.opsorchestra_jwt_issuer
        self._audience = audience or integration.opsorchestra_jwt_audience
        self._sub_claim = sub_claim or integration.opsorchestra_sub_claim
        self._tenant_claim = tenant_claim or integration.opsorchestra_tenant_claim
        self._tenant_claim_fallbacks = self._dedupe_claims(
            tenant_claim_fallbacks
            if tenant_claim_fallbacks is not None
            else integration.opsorchestra_tenant_claim_fallbacks
        )
        self._email_claim = email_claim or integration.opsorchestra_email_claim
        self._email_claim_fallbacks = self._dedupe_claims(
            email_claim_fallbacks
            if email_claim_fallbacks is not None
            else integration.opsorchestra_email_claim_fallbacks
        )
        self._roles_claim = roles_claim or integration.opsorchestra_roles_claim
        self._roles_claim_fallbacks = self._dedupe_claims(
            roles_claim_fallbacks
            if roles_claim_fallbacks is not None
            else integration.opsorchestra_roles_claim_fallbacks
        )
        self._require_email_claim = (
            require_email_claim
            if require_email_claim is not None
            else integration.opsorchestra_require_email_claim
        )
        self._require_roles_claim = (
            require_roles_claim
            if require_roles_claim is not None
            else integration.opsorchestra_require_roles_claim
        )
        self._public_key = self._load_public_key() if self._public_key_path else None
        if self._jwks_url:
            validate_remote_url(
                self._jwks_url,
                setting_name="INTEGRATION_OPSORCHESTRA_JWKS_URL",
                require_https=self._require_https,
                allow_private_network=self._allow_private_network,
            )
        self._jwks_cache: dict[str, rsa.RSAPublicKey] = {}
        self._jwks_cache_updated_at: float = 0.0
        if self._public_key is None and not self._jwks_url:
            raise ValueError(
                "OpsOrchestra auth requires INTEGRATION_OPSORCHESTRA_JWT_PUBLIC_KEY_PATH "
                "or INTEGRATION_OPSORCHESTRA_JWKS_URL"
            )

    def _load_public_key(self) -> rsa.RSAPublicKey:
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
            if " " in value:
                return [part.strip() for part in value.split(" ") if part.strip()]
            return [value] if value.strip() else []
        return []

    @staticmethod
    def _dedupe_claims(claim_names: list[str]) -> list[str]:
        deduped: list[str] = []
        for claim_name in claim_names:
            normalized = str(claim_name).strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    @staticmethod
    def _is_present(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return len(value) > 0
        return True

    def _first_present_claim(self, claims: dict[str, Any], claim_names: list[str]) -> Any:
        for claim_name in claim_names:
            value = claims.get(claim_name)
            if self._is_present(value):
                return value
        return None

    def _required_claim(self, claims: dict[str, Any], claim_names: list[str]) -> Any:
        value = self._first_present_claim(claims, claim_names)
        if self._is_present(value):
            return value
        formatted_claims = ", ".join(claim_names)
        raise AuthenticationError(
            message=f"Missing required claim: one of [{formatted_claims}]",
            code=ErrorCode.INVALID_TOKEN,
        )

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def _refresh_jwks_cache(self, *, force: bool = False) -> None:
        if not self._jwks_url:
            return

        now = time.time()
        is_fresh = (
            self._jwks_cache
            and (now - self._jwks_cache_updated_at) < self._jwks_cache_ttl_seconds
        )
        if not force and is_fresh:
            return

        payload: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = httpx.get(
                    self._jwks_url,
                    timeout=self._jwks_timeout_seconds,
                    headers={"Accept": "application/json", "User-Agent": "scalescore/0.1"},
                    follow_redirects=False,
                )
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ) as err:
                last_error = err
                if attempt >= self._max_retries:
                    break
                backoff_seconds = self._retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "opsorchestra_jwks_retryable_transport_error",
                    attempt=attempt + 1,
                    max_attempts=self._max_retries + 1,
                    backoff_seconds=round(backoff_seconds, 3),
                    error_type=type(err).__name__,
                )
                time.sleep(backoff_seconds)
                continue

            if self._is_retryable_status(response.status_code) and attempt < self._max_retries:
                backoff_seconds = self._retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "opsorchestra_jwks_retryable_response",
                    status_code=response.status_code,
                    attempt=attempt + 1,
                    max_attempts=self._max_retries + 1,
                    backoff_seconds=round(backoff_seconds, 3),
                )
                time.sleep(backoff_seconds)
                continue

            try:
                response.raise_for_status()
                payload = response.json()
                break
            except (httpx.HTTPError, ValueError) as err:
                last_error = err
                break

        if payload is None:
            if last_error is None:
                last_error = RuntimeError("JWKS response payload was empty")
            raise ScaleScoreError(
                message="Failed to fetch OpsOrchestra JWKS",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"jwks_url": self._jwks_url},
                cause=last_error,
            ) from last_error

        keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(keys, list):
            raise ScaleScoreError(
                message="Invalid JWKS payload from OpsOrchestra",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"jwks_url": self._jwks_url},
            )

        parsed_keys: dict[str, rsa.RSAPublicKey] = {}
        for jwk in keys:
            if not isinstance(jwk, dict):
                continue
            kid = jwk.get("kid")
            if not isinstance(kid, str) or not kid.strip():
                continue
            try:
                parsed_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(parsed_key, rsa.RSAPublicKey):
                parsed_keys[kid] = parsed_key

        if not parsed_keys:
            raise ScaleScoreError(
                message="No usable RSA keys found in OpsOrchestra JWKS",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"jwks_url": self._jwks_url},
            )

        self._jwks_cache = parsed_keys
        self._jwks_cache_updated_at = now

    def _public_key_for_token(self, token: str) -> rsa.RSAPublicKey:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as err:
            raise AuthenticationError(
                message="Invalid token",
                code=ErrorCode.INVALID_TOKEN,
                details={"reason": str(err)},
            ) from err

        algorithm = header.get("alg")
        if algorithm != "RS256":
            raise AuthenticationError(
                message="Unsupported token algorithm",
                code=ErrorCode.INVALID_TOKEN,
                details={"alg": algorithm},
            )

        if self._public_key is not None:
            return self._public_key

        kid = header.get("kid")
        if isinstance(kid, str) and kid.strip():
            self._refresh_jwks_cache()
            cached = self._jwks_cache.get(kid)
            if cached is not None:
                return cached
            self._refresh_jwks_cache(force=True)
            refreshed = self._jwks_cache.get(kid)
            if refreshed is not None:
                return refreshed
            raise AuthenticationError(
                message="Token key id is not available in JWKS",
                code=ErrorCode.INVALID_TOKEN,
                details={"kid": kid},
            )

        self._refresh_jwks_cache()
        if len(self._jwks_cache) == 1:
            return next(iter(self._jwks_cache.values()))
        raise AuthenticationError(
            message="Token header is missing required 'kid'",
            code=ErrorCode.INVALID_TOKEN,
        )

    def verify_parent_token(self, token: str) -> TokenPayload:
        public_key = self._public_key_for_token(token)
        try:
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._jwt_leeway_seconds,
                options={"require": ["exp", "iat"]},
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

        sub = self._required_claim(claims, [self._sub_claim])
        tenant_id = self._required_claim(
            claims,
            [self._tenant_claim, *self._tenant_claim_fallbacks],
        )
        email_claim_names = [self._email_claim, *self._email_claim_fallbacks]
        roles_claim_names = [self._roles_claim, *self._roles_claim_fallbacks]
        email_value = self._first_present_claim(claims, email_claim_names)
        roles_value = self._first_present_claim(claims, roles_claim_names)

        if self._require_email_claim:
            email_value = self._required_claim(claims, email_claim_names)
        if self._require_roles_claim:
            roles_value = self._required_claim(claims, roles_claim_names)

        email = str(email_value).strip() if self._is_present(email_value) else ""
        if not email:
            email = f"{sub}@opsorchestra.local"

        roles = self._as_roles(roles_value)
        if self._require_roles_claim and not roles:
            raise AuthenticationError(
                message=f"Missing required claim: {self._roles_claim}",
                code=ErrorCode.INVALID_TOKEN,
            )
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
