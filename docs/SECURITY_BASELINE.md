# ScaleScore Security Baseline

> **Date:** February 22, 2026  
> **Scope:** API and dependency baseline for Phase 2 readiness  
> **Status:** **Phase 2 security gate met** (OWASP API Top 10 self-audit completed)

---

## Objective

Maintain a repeatable baseline that verifies:
- Authentication and authorization controls
- Token and secret handling behavior
- Dependency vulnerability posture
- OWASP API Top 10 coverage evidence

This baseline is an engineering control set. It does not replace a third-party penetration test.

---

## Validation Performed

## 1) Dependency vulnerability scan

Command:

```bash
PYTHONPATH=src .venv/bin/pip-audit --progress-spinner off
```

Result:
- `No known vulnerabilities found`
- Local package `scalescore` skipped by `pip-audit` (expected for non-PyPI project package)

## 2) API regression and auth path tests

Command:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/e2e/test_api.py
```

Result:
- `29 passed`
- Coverage includes:
  - Auth-required route enforcement
  - Login/signup/refresh/API-key flows
  - OpsOrchestra JWT path and webhook secret handling
  - Assessment sync/pull integration endpoints
  - Async assessment queue submission and status flow
  - Async submission throttling, queue-cap enforcement, and upload-size limits
  - Scheduled assessment CRUD and scheduling controls

## 3) OWASP API Top 10 control audit

Reference:
- `docs/SECURITY_OWASP_API_TOP10_AUDIT.md`

Result:
- All 10 OWASP API categories mapped to concrete controls and tests
- Gate decision recorded as **PASS** on February 22, 2026

## 4) Code quality gate

Command:

```bash
PYTHONPATH=src .venv/bin/ruff check src tests
```

Result:
- `All checks passed`

---

## Findings

## F1: Webhook endpoint can be open in local/dev when no shared secret is configured

Severity: Medium  
Status: Accepted (environment-scoped)

Details:
- In production, missing secret returns `503` and blocks webhook processing.
- In local development, webhook secret can be omitted for convenience.

Mitigation:
- Require `INTEGRATION_OPSORCHESTRA_WEBHOOK_SECRET` in staging/production.
- Restrict ingress at network boundary for non-public environments.

## F2: No app-layer auth throttling (historical)

Severity: Medium  
Status: **Closed on February 22, 2026**

Closure:
- Added auth endpoint throttling for login/signup/refresh with configurable windows and limits.

---

## Security Controls Confirmed

- JWT + refresh-token rotation with reuse detection
- API keys stored by hash and revocable
- Tenant-scoped data access on protected routes
- Structured audit logging for auth and data operations
- OpsOrchestra URL hardening (HTTPS enforcement in staging/production and private-network guardrails)
- Connector/JWKS retry boundaries with fail-closed behavior
- Auth endpoint throttling
- Async assessment abuse controls (submit throttling, queue cap, per-file upload size)

---

## Next Actions

1. Enforce edge-level rate limits and body-size limits in staging/production ingress.
2. Keep `docs/STAGING_VALIDATION.md` as required pre-release checklist.
3. Schedule external penetration testing in the enterprise readiness phase.
