# ScaleScore Security Baseline

> **Date:** February 22, 2026  
> **Scope:** API and dependency security baseline for Phase 2 readiness  
> **Status:** Baseline complete, full OWASP audit still pending

---

## Objective

Establish a repeatable baseline that validates core API security controls before Phase 3 integration work:
- Authentication and authorization guard coverage
- Token and secret handling behavior
- Dependency vulnerability status

This is not a full penetration test and does not replace a formal OWASP audit.

---

## Validation Performed

## 1) Dependency vulnerability scan

Command:

```bash
PYTHONPATH=src .venv/bin/pip-audit --progress-spinner off
```

Result:
- `No known vulnerabilities found`
- Local package `scalescore` is skipped by `pip-audit` (expected for non-PyPI project package)

## 2) End-to-end API auth and permission regression tests

Command:

```bash
PYTHONPATH=src .venv/bin/pytest tests/e2e/test_api.py -q
```

Result:
- `15 passed`
- Coverage includes:
  - Protected assessment endpoints reject unauthenticated access
  - Login/signup/refresh/API-key flows
  - Organization CRUD with authenticated principal
  - Webhook secret enforcement tests

## 3) OpenAPI exposure review

Observed unauthenticated routes:
- `POST /api/v1/auth/signup`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/webhooks/opsorchestra` (header-based secret when configured)
- `GET /api/v1/health`

Assessment:
- Expected for login/signup/refresh/health.
- Webhook route behavior is environment/secret-config dependent and needs explicit deployment guidance.

---

## Findings

## F1: Webhook endpoint can be open when no shared secret is configured outside production

Severity: Medium  
Status: Accepted with mitigation required

Details:
- In production, missing webhook secret returns `503` and blocks processing.
- In development/staging-like environments with no secret configured, webhook requests are accepted.

Risk:
- If a non-production environment is externally reachable, untrusted callers could send synthetic webhook events.

Mitigation:
- Set `INTEGRATION_OPSORCHESTRA_WEBHOOK_SECRET` for every non-local environment.
- Restrict webhook ingress at network boundary (allow-list source IPs or private ingress).
- Keep new CI tests enforcing secret behavior.

## F2: No API rate limiting controls in application layer

Severity: Medium  
Status: Open

Details:
- No per-IP or per-principal throttling exists in API middleware.

Risk:
- Brute-force or resource-abuse attempts rely entirely on external gateway controls.

Mitigation:
- Add gateway/WAF rate limits immediately.
- Add application-layer rate limiting for auth endpoints in a future milestone.

---

## Security Controls Confirmed

- JWT + refresh-token rotation implemented
- Refresh token reuse detection triggers user-wide token revocation
- API keys are stored by hash and revocable
- Tenant-scoped repository access patterns enforced in protected routes
- Structured audit logging for auth and data operations
- CI includes `pip-audit`

---

## Recommended Next Actions (P0/P1)

1. P0: Enforce webhook secret in every non-local deployed environment.
2. P0: Add API/gateway rate limiting policy for auth and assessment routes.
3. P1: Run formal OWASP Top 10 API audit and capture evidence in this document.
4. P1: Add abuse-case tests (token brute-force thresholds, oversized uploads, webhook replay protection).
