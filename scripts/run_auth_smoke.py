#!/usr/bin/env python3
"""Run auth smoke checks against a live ScaleScore API instance."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives import serialization


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run auth smoke checks against ScaleScore.")
    parser.add_argument(
        "--mode",
        choices=("internal-jwt", "external-oidc"),
        required=True,
        help="Smoke-check mode to execute.",
    )
    parser.add_argument("--base-url", required=True, help="ScaleScore API base URL.")
    parser.add_argument("--result-path", required=True, help="JSON output path for smoke result.")
    parser.add_argument(
        "--token-output-path",
        help="Optional output path for the retrieved internal JWT access token.",
    )
    parser.add_argument(
        "--private-key-path",
        help="PEM private key path for external OIDC token issuance.",
    )
    parser.add_argument(
        "--issuer",
        default="https://idp.example.com/",
        help="Token issuer for external OIDC mode.",
    )
    parser.add_argument(
        "--audience",
        default="scalescore-api",
        help="Token audience for external OIDC mode.",
    )
    return parser.parse_args()


def _write_result(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_internal_jwt_smoke(
    *,
    base_url: str,
    result_path: Path,
    token_output_path: Path | None,
) -> int:
    result: dict[str, object] = {
        "base_url": base_url,
        "mode": "internal-jwt",
        "status": "FAIL",
    }
    email = f"ci-{int(time.time())}-{uuid.uuid4().hex[:8]}@example.com"
    password = "strong-password"

    try:
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            signup_response = client.post(
                "/api/v1/auth/signup",
                json={
                    "email": email,
                    "password": password,
                    "tenant_id": "tenant-ci",
                    "org_id": "org-ci",
                    "roles": ["analyst"],
                },
            )
            result["signup_status_code"] = signup_response.status_code
            if signup_response.status_code != 201:
                result["signup_body"] = signup_response.text[:1000]
                raise RuntimeError("signup failed")

            login_response = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": password},
            )
            result["login_status_code"] = login_response.status_code
            if login_response.status_code != 200:
                result["login_body"] = login_response.text[:1000]
                raise RuntimeError("login failed")

            access_token = login_response.json().get("access_token")
            if not access_token:
                raise RuntimeError("login response missing access_token")

            protected_response = client.get(
                "/api/v1/assessments",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            result["protected_status_code"] = protected_response.status_code
            if protected_response.status_code != 200:
                result["protected_body"] = protected_response.text[:1000]
                raise RuntimeError("protected endpoint failed")

            if token_output_path is not None:
                token_output_path.parent.mkdir(parents=True, exist_ok=True)
                token_output_path.write_text(access_token + "\n", encoding="utf-8")

        result["status"] = "PASS"
    except Exception as err:  # noqa: BLE001
        result["error"] = str(err)
        _write_result(result_path, result)
        return 1

    _write_result(result_path, result)
    return 0


def _run_external_oidc_smoke(
    *,
    base_url: str,
    result_path: Path,
    private_key_path: Path,
    issuer: str,
    audience: str,
) -> int:
    result: dict[str, object] = {
        "base_url": base_url,
        "mode": "external-oidc",
        "status": "FAIL",
    }

    try:
        private_key = serialization.load_pem_private_key(
            private_key_path.read_bytes(),
            password=None,
        )
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "oidc-ci-user",
                "tid": "tenant-ci-oidc",
                "email": "oidc-ci@example.com",
                "groups": ["admin"],
                "iat": now,
                "exp": now + timedelta(minutes=10),
                "iss": issuer,
                "aud": audience,
            },
            private_key,
            algorithm="RS256",
        )

        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            response = client.get(
                "/api/v1/assessments",
                headers={"Authorization": f"Bearer {token}"},
            )
            result["status_code"] = response.status_code
            if response.status_code != 200:
                result["body"] = response.text[:1000]
                raise RuntimeError("external OIDC protected endpoint returned non-200")

        result["status"] = "PASS"
    except Exception as err:  # noqa: BLE001
        result["error"] = str(err)
        _write_result(result_path, result)
        return 1

    _write_result(result_path, result)
    return 0


def main() -> int:
    args = parse_args()
    result_path = Path(args.result_path)

    if args.mode == "internal-jwt":
        token_output_path = Path(args.token_output_path) if args.token_output_path else None
        return _run_internal_jwt_smoke(
            base_url=args.base_url,
            result_path=result_path,
            token_output_path=token_output_path,
        )

    if not args.private_key_path:
        raise RuntimeError("--private-key-path is required for external-oidc mode")

    return _run_external_oidc_smoke(
        base_url=args.base_url,
        result_path=result_path,
        private_key_path=Path(args.private_key_path),
        issuer=args.issuer,
        audience=args.audience,
    )


if __name__ == "__main__":
    raise SystemExit(main())
