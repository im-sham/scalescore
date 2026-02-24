from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scalescore.config import settings
from scalescore.core.auth.external_oidc import ExternalOIDCAuthService


def _write_public_key(path) -> rsa.RSAPrivateKey:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.write_bytes(public_key_bytes)
    return private_key


def test_verify_token_maps_claims(tmp_path) -> None:
    public_key_path = tmp_path / "idp-public.pem"
    private_key = _write_public_key(public_key_path)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "oidc_sub": "oidc-user-1",
            "tid": "tenant-oidc",
            "preferred_username": "oidc-user@example.com",
            "groups": ["admin", "analyst"],
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "https://idp.example.com/",
            "aud": "scalescore-api",
        },
        private_key,
        algorithm="RS256",
    )

    service = ExternalOIDCAuthService(
        provider_name="auth0",
        public_key_path=str(public_key_path),
        issuer="https://idp.example.com/",
        audience="scalescore-api",
        sub_claim="oidc_sub",
        tenant_claim="tid",
        email_claim="preferred_username",
        roles_claim="groups",
    )

    payload = service.verify_token(token)
    assert payload.sub == "oidc-user-1"
    assert payload.tenant_id == "tenant-oidc"
    assert payload.email == "oidc-user@example.com"
    assert payload.roles == ["admin", "analyst"]


def test_verify_token_uses_provider_domain_for_default_email(tmp_path) -> None:
    public_key_path = tmp_path / "idp-public.pem"
    private_key = _write_public_key(public_key_path)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "oidc-user-2",
            "tenant_id": "tenant-oidc",
            "roles": ["viewer"],
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "https://idp.example.com/",
            "aud": "scalescore-api",
        },
        private_key,
        algorithm="RS256",
    )

    service = ExternalOIDCAuthService(
        provider_name="Auth0",
        public_key_path=str(public_key_path),
        issuer="https://idp.example.com/",
        audience="scalescore-api",
        require_email_claim=False,
    )

    payload = service.verify_token(token)
    assert payload.email == "oidc-user-2@auth0.local"


def test_requires_issuer_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    public_key_path = tmp_path / "idp-public.pem"
    _write_public_key(public_key_path)
    monkeypatch.setattr(settings.integration, "external_oidc_jwt_issuer", "")

    with pytest.raises(ValueError, match="INTEGRATION_EXTERNAL_OIDC_JWT_ISSUER"):
        ExternalOIDCAuthService(public_key_path=str(public_key_path))
