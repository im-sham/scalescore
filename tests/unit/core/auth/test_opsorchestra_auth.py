from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scalescore.core.auth.opsorchestra import OpsOrchestraAuthService
from scalescore.core.exceptions import AuthenticationError, ErrorCode


def _write_public_key(path) -> rsa.RSAPrivateKey:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.write_bytes(public_key_bytes)
    return private_key


def test_verify_parent_token_maps_claims(tmp_path) -> None:
    public_key_path = tmp_path / "opsorchestra-public.pem"
    private_key = _write_public_key(public_key_path)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub_id": "ops-user-1",
            "tenant": "tenant-ops",
            "mail": "ops@example.com",
            "groups": ["admin", "analyst"],
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "opsorchestra",
            "aud": "scalescore-api",
        },
        private_key,
        algorithm="RS256",
    )

    service = OpsOrchestraAuthService(
        public_key_path=str(public_key_path),
        issuer="opsorchestra",
        audience="scalescore-api",
        sub_claim="sub_id",
        tenant_claim="tenant",
        email_claim="mail",
        roles_claim="groups",
    )

    payload = service.verify_parent_token(token)
    assert payload.sub == "ops-user-1"
    assert payload.tenant_id == "tenant-ops"
    assert payload.email == "ops@example.com"
    assert payload.roles == ["admin", "analyst"]


def test_verify_parent_token_requires_tenant_claim(tmp_path) -> None:
    public_key_path = tmp_path / "opsorchestra-public.pem"
    private_key = _write_public_key(public_key_path)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "ops-user-1",
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "opsorchestra",
            "aud": "scalescore-api",
        },
        private_key,
        algorithm="RS256",
    )

    service = OpsOrchestraAuthService(
        public_key_path=str(public_key_path),
        issuer="opsorchestra",
        audience="scalescore-api",
    )

    with pytest.raises(AuthenticationError) as exc_info:
        service.verify_parent_token(token)
    assert exc_info.value.code == ErrorCode.INVALID_TOKEN


def test_verify_parent_token_rejects_invalid_signature(tmp_path) -> None:
    trusted_public_key_path = tmp_path / "trusted-public.pem"
    _write_public_key(trusted_public_key_path)

    attacker_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "ops-user-1",
            "tenant_id": "tenant-ops",
            "roles": ["admin"],
            "email": "ops@example.com",
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "opsorchestra",
            "aud": "scalescore-api",
        },
        attacker_private_key,
        algorithm="RS256",
    )

    service = OpsOrchestraAuthService(
        public_key_path=str(trusted_public_key_path),
        issuer="opsorchestra",
        audience="scalescore-api",
    )

    with pytest.raises(AuthenticationError) as exc_info:
        service.verify_parent_token(token)
    assert exc_info.value.code == ErrorCode.INVALID_TOKEN
