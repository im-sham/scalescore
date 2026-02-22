from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from scalescore.core.auth.opsorchestra import OpsOrchestraAuthService
from scalescore.core.exceptions import AuthenticationError, ErrorCode, ScaleScoreError


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


def test_verify_parent_token_via_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "ops-key-1"
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = kid

    def _fake_httpx_get(url: str, timeout: float, headers: dict[str, str]) -> httpx.Response:
        assert "jwks" in url
        return httpx.Response(
            status_code=200,
            json={"keys": [jwk]},
            request=httpx.Request("GET", url),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr("scalescore.core.auth.opsorchestra.httpx.get", _fake_httpx_get)

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "ops-user-1",
            "tenant_id": "tenant-ops",
            "email": "ops@example.com",
            "roles": ["admin"],
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "opsorchestra",
            "aud": "scalescore-api",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    service = OpsOrchestraAuthService(
        public_key_path=None,
        jwks_url="https://opsorchestra.example/.well-known/jwks.json",
        issuer="opsorchestra",
        audience="scalescore-api",
    )
    payload = service.verify_parent_token(token)
    assert payload.sub == "ops-user-1"
    assert payload.tenant_id == "tenant-ops"


def test_verify_parent_token_jwks_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "ops-user-1",
            "tenant_id": "tenant-ops",
            "email": "ops@example.com",
            "roles": ["admin"],
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "iss": "opsorchestra",
            "aud": "scalescore-api",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "ops-key-1"},
    )

    def _failing_httpx_get(url: str, timeout: float, headers: dict[str, str]) -> httpx.Response:
        raise httpx.ConnectError("failed", request=httpx.Request("GET", url))

    monkeypatch.setattr("scalescore.core.auth.opsorchestra.httpx.get", _failing_httpx_get)

    service = OpsOrchestraAuthService(
        public_key_path=None,
        jwks_url="https://opsorchestra.example/.well-known/jwks.json",
        issuer="opsorchestra",
        audience="scalescore-api",
    )
    with pytest.raises(ScaleScoreError) as exc_info:
        service.verify_parent_token(token)
    assert exc_info.value.code == ErrorCode.EXTERNAL_SERVICE_ERROR


def test_verify_parent_token_requires_email_when_enforced(tmp_path) -> None:
    public_key_path = tmp_path / "opsorchestra-public.pem"
    private_key = _write_public_key(public_key_path)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "ops-user-1",
            "tenant_id": "tenant-ops",
            "roles": ["admin"],
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
        require_email_claim=True,
    )
    with pytest.raises(AuthenticationError) as exc_info:
        service.verify_parent_token(token)
    assert exc_info.value.code == ErrorCode.INVALID_TOKEN


def test_verify_parent_token_requires_roles_when_enforced(tmp_path) -> None:
    public_key_path = tmp_path / "opsorchestra-public.pem"
    private_key = _write_public_key(public_key_path)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "ops-user-1",
            "tenant_id": "tenant-ops",
            "email": "ops@example.com",
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
        require_roles_claim=True,
    )
    with pytest.raises(AuthenticationError) as exc_info:
        service.verify_parent_token(token)
    assert exc_info.value.code == ErrorCode.INVALID_TOKEN


def test_verify_parent_token_uses_defaults_when_optional_claims_disabled(tmp_path) -> None:
    public_key_path = tmp_path / "opsorchestra-public.pem"
    private_key = _write_public_key(public_key_path)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "ops-user-1",
            "tenant_id": "tenant-ops",
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
        require_email_claim=False,
        require_roles_claim=False,
    )
    payload = service.verify_parent_token(token)
    assert payload.email == "ops-user-1@opsorchestra.local"
    assert payload.roles == ["viewer"]
