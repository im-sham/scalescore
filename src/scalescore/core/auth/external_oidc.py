from __future__ import annotations

import re
from functools import lru_cache

from scalescore.config import settings
from scalescore.core.auth.jwt import TokenPayload
from scalescore.core.auth.opsorchestra import OpsOrchestraAuthService


class ExternalOIDCAuthService:
    """
    Provider-neutral external OIDC JWT verifier.

    This is a scaffold that reuses the existing upstream JWT verification flow so
    managed SSO providers can be added without coupling business logic to one IdP.
    """

    def __init__(
        self,
        *,
        provider_name: str | None = None,
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
        self._provider_name = (provider_name or integration.external_oidc_provider_name).strip()
        if not self._provider_name:
            self._provider_name = "external-oidc"

        issuer_value = (issuer if issuer is not None else integration.external_oidc_jwt_issuer).strip()
        if not issuer_value:
            raise ValueError(
                "INTEGRATION_EXTERNAL_OIDC_JWT_ISSUER is required when "
                "INTEGRATION_EXTERNAL_OIDC_AUTH_ENABLED=true"
            )

        try:
            self._delegate = OpsOrchestraAuthService(
                public_key_path=public_key_path or integration.external_oidc_jwt_public_key_path,
                jwks_url=jwks_url or integration.external_oidc_jwks_url,
                jwks_timeout_seconds=(
                    jwks_timeout_seconds
                    if jwks_timeout_seconds is not None
                    else integration.external_oidc_jwks_timeout_seconds
                ),
                jwks_cache_ttl_seconds=(
                    jwks_cache_ttl_seconds
                    if jwks_cache_ttl_seconds is not None
                    else integration.external_oidc_jwks_cache_ttl_seconds
                ),
                jwt_leeway_seconds=(
                    jwt_leeway_seconds
                    if jwt_leeway_seconds is not None
                    else integration.external_oidc_jwt_leeway_seconds
                ),
                tenant_claim_fallbacks=(
                    tenant_claim_fallbacks
                    if tenant_claim_fallbacks is not None
                    else integration.external_oidc_tenant_claim_fallbacks
                ),
                email_claim_fallbacks=(
                    email_claim_fallbacks
                    if email_claim_fallbacks is not None
                    else integration.external_oidc_email_claim_fallbacks
                ),
                roles_claim_fallbacks=(
                    roles_claim_fallbacks
                    if roles_claim_fallbacks is not None
                    else integration.external_oidc_roles_claim_fallbacks
                ),
                allow_private_network=(
                    allow_private_network
                    if allow_private_network is not None
                    else integration.external_oidc_allow_private_network
                ),
                issuer=issuer_value,
                audience=audience or integration.external_oidc_jwt_audience,
                sub_claim=sub_claim or integration.external_oidc_sub_claim,
                tenant_claim=tenant_claim or integration.external_oidc_tenant_claim,
                email_claim=email_claim or integration.external_oidc_email_claim,
                roles_claim=roles_claim or integration.external_oidc_roles_claim,
                require_email_claim=(
                    require_email_claim
                    if require_email_claim is not None
                    else integration.external_oidc_require_email_claim
                ),
                require_roles_claim=(
                    require_roles_claim
                    if require_roles_claim is not None
                    else integration.external_oidc_require_roles_claim
                ),
            )
        except ValueError as err:
            if "OpsOrchestra auth requires" not in str(err):
                raise
            raise ValueError(
                "External OIDC auth requires INTEGRATION_EXTERNAL_OIDC_JWT_PUBLIC_KEY_PATH "
                "or INTEGRATION_EXTERNAL_OIDC_JWKS_URL"
            ) from err

        self._default_email_domain = self._derive_default_email_domain(self._provider_name)

    @staticmethod
    def _derive_default_email_domain(provider_name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", provider_name.lower()).strip("-")
        if not slug:
            slug = "external-oidc"
        return f"{slug}.local"

    def verify_token(self, token: str) -> TokenPayload:
        payload = self._delegate.verify_parent_token(token)
        # The delegated verifier uses an OpsOrchestra default email domain when the
        # email claim is optional and missing. Re-map to the configured provider.
        if payload.email.endswith("@opsorchestra.local"):
            payload.email = f"{payload.sub}@{self._default_email_domain}"
        payload.auth_method = "external_oidc"
        return payload


@lru_cache
def get_external_oidc_auth_service() -> ExternalOIDCAuthService:
    return ExternalOIDCAuthService()
