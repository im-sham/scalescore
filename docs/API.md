# Proofhouse Readiness API Reference

> **Last Updated:** March 9, 2026  
> **Version:** v1 (`/api/v1`)

---

## Overview

Proofhouse Readiness currently ships through the `scalescore` FastAPI service, which provides:
- Authentication and API key management
- Running and retrieving assessments
- Managing organizations and entities
- Importing CSV data
- Receiving OpsOrchestra webhook events

Readiness is transitioning to a workflow-first AI operational readiness model. The current HTTP API remains backward compatible, continues to support organization-level assessments, and now exposes additive workflow-first submission paths.

Current compatibility rules:

- existing org-level endpoints remain supported
- existing CSV upload and demo flows remain supported
- workflow-first report fields may appear on `ScaleScoreReport` payloads when reports are generated with workflow context via HTTP workflow submission endpoints or the Python/internal contract
- legacy `OpsOrchestra` and `ScaleScore` naming remains in some integration settings for backward compatibility, but user-facing narrative should prefer `Workflow Context` / `Proofhouse`
- repo/package/env/auth/API identifiers remain `scalescore` in this phase; the planned repo-root rename to `proofhouse-readiness` is a separate later wave

Base URL (local): `http://localhost:8000`

OpenAPI endpoints:
- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`
- OpenAPI JSON: `GET /openapi.json`

---

## Local Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Optional for broker worker mode:
# pip install -e ".[dev,worker]"
cp .env.example .env
uvicorn scalescore.api.main:app --reload
```

Note: `.env.example` sets `AUTH_SKIP_AUTH=true` for development convenience.

---

## Authentication

The current `scalescore` service supports two auth methods:
- `Authorization: Bearer <access_token>`
- `X-API-Key: <api_key>`

### Deployment auth modes

| Scenario | Auth path | Auth0 required? |
|---|---|---|
| Local development | Internal auth (`/api/v1/auth/*`) or dev bypass (`AUTH_SKIP_AUTH=true`) | No |
| Open-source/self-hosted production | Internal JWT + refresh + API keys | No |
| OpsOrchestra-integrated deployment | Internal auth and/or trusted OpsOrchestra JWT mode | No |
| Managed SSO deployment (optional) | Standards-based OIDC provider integration (Auth0 or equivalent) | Optional |

ScaleScore's open-source baseline does not require Auth0. External IdP integration is an optional deployment profile and should remain provider-neutral. See [ADR-0017](./adr/0017-open-source-auth-provider-strategy.md).

Optional integration mode:
- OpsOrchestra-issued Bearer JWTs can be accepted on protected routes when
  `INTEGRATION_OPSORCHESTRA_AUTH_ENABLED=true` and a trusted static public key or JWKS URL is configured.

Auth abuse controls:
- Login/signup/refresh endpoints are protected by application-layer rate limits.
- Limits are configurable via `AUTH_*_RATE_LIMIT_*` settings.

### Development bypass

If `AUTH_SKIP_AUTH=true` and `ENVIRONMENT=development`, permission checks use an internal dev admin principal.

For auth integration testing, set:

```bash
AUTH_SKIP_AUTH=false
```

and restart the API.

Auth rate-limit settings:

```bash
AUTH_LOGIN_RATE_LIMIT_REQUESTS=120
AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS=60
AUTH_SIGNUP_RATE_LIMIT_REQUESTS=30
AUTH_SIGNUP_RATE_LIMIT_WINDOW_SECONDS=3600
AUTH_REFRESH_RATE_LIMIT_REQUESTS=120
AUTH_REFRESH_RATE_LIMIT_WINDOW_SECONDS=60
```

Async assessment worker and abuse-control settings:

```bash
FEATURE_ENABLE_ASYNC_ASSESSMENTS=true
ASYNC_ASSESSMENT_MODE=poll  # poll | background | broker
ASYNC_ASSESSMENT_WORKER_POLL_INTERVAL_SECONDS=0.25

# Broker mode requires Redis URL (use rediss:// in staging/production)
# ASYNC_ASSESSMENT_BROKER_URL=redis://localhost:6379/0
ASYNC_ASSESSMENT_BROKER_QUEUE_NAME=scalescore:async-assessment:jobs
ASYNC_ASSESSMENT_BROKER_DEQUEUE_TIMEOUT_SECONDS=5
ASYNC_ASSESSMENT_SCHEDULED_DISPATCH_POLL_INTERVAL_SECONDS=30
ASYNC_ASSESSMENT_SCHEDULED_DISPATCH_BATCH_SIZE=10

ASYNC_ASSESSMENT_SUBMIT_RATE_LIMIT_REQUESTS=60
ASYNC_ASSESSMENT_SUBMIT_RATE_LIMIT_WINDOW_SECONDS=60
ASYNC_ASSESSMENT_MAX_OUTSTANDING_JOBS_PER_TENANT=25
ASYNC_ASSESSMENT_MAX_UPLOAD_BYTES_PER_FILE=5000000
```

### Token flow

1. `POST /api/v1/auth/signup`
2. `POST /api/v1/auth/login`
3. Use `access_token` as Bearer token
4. Rotate with `POST /api/v1/auth/refresh`

### OpsOrchestra JWT mode

When enabled, ScaleScore falls back to verifying Bearer tokens with OpsOrchestra settings:

```bash
INTEGRATION_OPSORCHESTRA_AUTH_ENABLED=true

# Configure either static key path OR JWKS URL
INTEGRATION_OPSORCHESTRA_JWT_PUBLIC_KEY_PATH=/path/to/opsorchestra-public.pem
# INTEGRATION_OPSORCHESTRA_JWKS_URL=https://opsorchestra.example.com/.well-known/jwks.json
INTEGRATION_OPSORCHESTRA_JWKS_TIMEOUT_SECONDS=5
INTEGRATION_OPSORCHESTRA_JWKS_CACHE_TTL_SECONDS=300
INTEGRATION_OPSORCHESTRA_JWT_LEEWAY_SECONDS=30

INTEGRATION_OPSORCHESTRA_JWT_ISSUER=opsorchestra
INTEGRATION_OPSORCHESTRA_JWT_AUDIENCE=scalescore-api
INTEGRATION_OPSORCHESTRA_SUB_CLAIM=sub
INTEGRATION_OPSORCHESTRA_TENANT_CLAIM=tenant_id
INTEGRATION_OPSORCHESTRA_TENANT_CLAIM_FALLBACKS=["tenant","tid"]
INTEGRATION_OPSORCHESTRA_EMAIL_CLAIM=email
INTEGRATION_OPSORCHESTRA_EMAIL_CLAIM_FALLBACKS=["upn","preferred_username"]
INTEGRATION_OPSORCHESTRA_ROLES_CLAIM=roles
INTEGRATION_OPSORCHESTRA_ROLES_CLAIM_FALLBACKS=["groups","scope","scp"]
INTEGRATION_OPSORCHESTRA_REQUIRE_EMAIL_CLAIM=true
INTEGRATION_OPSORCHESTRA_REQUIRE_ROLES_CLAIM=true
```

### External OIDC JWT mode (provider-neutral scaffold)

For managed SSO deployments, ScaleScore can optionally verify upstream OIDC JWTs
using static key or JWKS configuration without binding to a specific vendor:

```bash
INTEGRATION_EXTERNAL_OIDC_AUTH_ENABLED=true
INTEGRATION_EXTERNAL_OIDC_PROVIDER_NAME=auth0

# Configure either static key path OR JWKS URL
# INTEGRATION_EXTERNAL_OIDC_JWT_PUBLIC_KEY_PATH=/path/to/idp-public.pem
INTEGRATION_EXTERNAL_OIDC_JWKS_URL=https://idp.example.com/.well-known/jwks.json

INTEGRATION_EXTERNAL_OIDC_JWT_ISSUER=https://idp.example.com/
INTEGRATION_EXTERNAL_OIDC_JWT_AUDIENCE=scalescore-api
INTEGRATION_EXTERNAL_OIDC_TENANT_CLAIM=tenant_id
INTEGRATION_EXTERNAL_OIDC_ROLES_CLAIM=roles
```

---

## Roles and Permissions

| Role | Effective permissions |
|------|------------------------|
| `viewer` | `assessment:read`, `report:view` |
| `analyst` | Viewer + `assessment:create`, `report:export` |
| `admin` | Analyst + `assessment:delete`, `organization:manage`, `user:manage`, `user:view`, `audit:view` |
| `super_admin` | All permissions |

Most business endpoints require one of:
- `assessment:create`
- `assessment:read`
- `report:export`
- `organization:manage`

---

## Endpoint Matrix

### Workflow-first compatibility note

The workflow-first contract is additive and now available on the HTTP surface without removing the existing organization assessment paths:

- `workflow_context`
- `workflow_readiness_score`
- `workflow_readiness_grade`
- `workflow_pillar_scores`
- `top_trust_gaps`
- `prioritized_remediation_actions`
- `operational_learning_suitability`
- `org_rollup`

Current compatibility rules:

- `POST /api/v1/assessments` remains the development-only org-compatibility path using `dataset_path`
- `POST /api/v1/assessments/workflow` accepts `dataset_path` plus `workflow_context` as JSON
- `POST /api/v1/assessments/mila/workflow` is the current Workflow Context compatibility endpoint and accepts direct workflow metadata without requiring dataset CSVs
  Optional `workflow_evidence` can be supplied to deepen pillar scoring from source evidence. This now supports explicit `control_coverage` (`approval_gate`, `decision_logging`, `evidence_retention`, `exception_handling`, `periodic_review` with `missing|documented|operating|verified`) and `evidence_posture` (`control_evidence_coverage_percent`, `freshest_evidence_age_days`, `audit_trail_complete`, `linked_artifacts`), with legacy approval/decision counts retained as fallback
  Optional `operational_learning_inputs` can be supplied to add a separate operational-learning suitability block. Supported v1 inputs are `sop_reference_present`, `sop_clarity_signal`, `outcome_spec_present`, `outcome_observability_signal`, `run_frequency_per_week` or `repeatability_signal`, `review_path_present` or `review_density_signal`, `redaction_manageability_signal`, and `governance_dependency_state` (`rights_completeness`, `provenance_completeness`, `redaction_readiness`, `residual_risk_band`)
- `POST /api/v1/assessments/upload` still accepts the six CSV files and now supports optional `workflow_context_json` form data for workflow scoring
- `POST /api/v1/assessments/async/upload` supports optional `workflow_context_json` and echoes workflow context on job-status payloads
- `POST /api/v1/assessments/schedules/upload` supports optional `workflow_context_json` and persists workflow context on schedule payloads

## Health

| Method | Path | Auth | Notes |
|-------|------|------|-------|
| `GET` | `/api/v1/health` | No | Liveness/status |

## Auth

| Method | Path | Auth | Notes |
|-------|------|------|-------|
| `POST` | `/api/v1/auth/signup` | No | Create user |
| `POST` | `/api/v1/auth/login` | No | Email/password login |
| `GET` | `/api/v1/auth/me` | Bearer/API key | Current user |
| `POST` | `/api/v1/auth/refresh` | No | Rotate refresh token |
| `POST` | `/api/v1/auth/logout` | Bearer/API key | Optional refresh token revocation |
| `GET` | `/api/v1/auth/api-keys` | Bearer/API key | List keys for current user |
| `POST` | `/api/v1/auth/api-keys` | Bearer/API key | Create key |
| `DELETE` | `/api/v1/auth/api-keys/{key_id}` | Bearer/API key | Revoke key |

## Assessments

| Method | Path | Required permission | Notes |
|-------|------|---------------------|-------|
| `POST` | `/api/v1/assessments` | `assessment:create` | Requires `dataset_path`; development-only path execution |
| `POST` | `/api/v1/assessments/workflow` | `assessment:create` | JSON workflow submission (`dataset_path` + `workflow_context`); development-only dataset path execution |
| `POST` | `/api/v1/assessments/mila/workflow` | `assessment:create` | Workflow Context compatibility submission (`org_id`, `org_name`, `workflow_context`, optional `workflow_evidence`, optional `operational_learning_inputs`, optional baseline findings); no CSV dataset required |
| `POST` | `/api/v1/assessments/upload` | `assessment:create` | Multipart upload of six CSV files; optional `workflow_context_json` form field enables workflow scoring |
| `POST` | `/api/v1/assessments/async/upload` | `assessment:create` | Queue async assessment job (`202 Accepted`); optional `workflow_context_json` enables workflow scoring |
| `GET` | `/api/v1/assessments/async/{job_id}` | `assessment:read` | Poll queued/processing/completed async job status; echoes workflow context when present |
| `POST` | `/api/v1/assessments/schedules/upload` | `assessment:create` | Create scheduled assessment from CSV upload (`daily`/`weekly`); optional `workflow_context_json` enables workflow scoring |
| `GET` | `/api/v1/assessments/schedules` | `assessment:read` | List scheduled assessments for tenant, including workflow context when present |
| `GET` | `/api/v1/assessments/schedules/{schedule_id}` | `assessment:read` | Get scheduled assessment, including workflow context when present |
| `POST` | `/api/v1/assessments/schedules/{schedule_id}/pause` | `assessment:create` | Pause scheduled assessment |
| `POST` | `/api/v1/assessments/schedules/{schedule_id}/resume` | `assessment:create` | Resume scheduled assessment |
| `GET` | `/api/v1/assessments` | `assessment:read` | Pagination via `limit`, `offset` |
| `GET` | `/api/v1/assessments/{assessment_id}` | `assessment:read` | Retrieve saved report |
| `GET` | `/api/v1/assessments/{assessment_id}/export/pdf` | `report:export` | Download PDF |
| `POST` | `/api/v1/assessments/{assessment_id}/sync/opsorchestra` | `report:export` | Push report summary and top findings to configured OpsOrchestra outbound URL |

## Organizations

| Method | Path | Required permission | Notes |
|-------|------|---------------------|-------|
| `POST` | `/api/v1/organizations` | `organization:manage` | Upsert organization |
| `GET` | `/api/v1/organizations` | `assessment:read` | List organizations |
| `GET` | `/api/v1/organizations/{org_id}` | `assessment:read` | Read organization |
| `PUT` | `/api/v1/organizations/{org_id}` | `organization:manage` | Full update |
| `DELETE` | `/api/v1/organizations/{org_id}` | `organization:manage` | Delete organization |

## Entities (`team`, `system`, `vendor`, `facility`, `role`, `process`)

| Method | Path | Required permission | Notes |
|-------|------|---------------------|-------|
| `POST` | `/api/v1/entities/{entity_type}` | `organization:manage` | Create entity |
| `GET` | `/api/v1/entities/{entity_type}` | `assessment:read` | List by type, optional `org_id` |
| `GET` | `/api/v1/entities/{entity_type}/{entity_id}` | `assessment:read` | Get entity |
| `PUT` | `/api/v1/entities/{entity_type}/{entity_id}` | `organization:manage` | Update entity |
| `DELETE` | `/api/v1/entities/{entity_type}/{entity_id}` | `organization:manage` | Delete entity |

## Analytics and Import

| Method | Path | Required permission | Notes |
|-------|------|---------------------|-------|
| `GET` | `/api/v1/scores/{org_id}/history` | `assessment:read` | Trend windows: 7d/30d/90d |
| `POST` | `/api/v1/import/csv` | `assessment:create` | Multipart CSV import by `entity_type` (`organization`, `team`, `system`, `vendor`, `facility`) |

## Integration

| Method | Path | Auth | Notes |
|-------|------|------|-------|
| `POST` | `/api/v1/integrations/opsorchestra/pull` | Bearer/API key + `organization:manage` | Pull org/entities from configured OpsOrchestra graph export endpoint |
| `POST` | `/api/v1/webhooks/opsorchestra` | `X-Webhook-Secret` when configured | Upserts/deletes entities from events |

---

## Example Workflow (Bearer Auth)

Set base URL:

```bash
export BASE_URL="http://localhost:8000"
```

Create user:

```bash
curl -sS -X POST "$BASE_URL/api/v1/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "analyst@example.com",
    "password": "strong-password",
    "tenant_id": "tenant-demo",
    "org_id": "org-demo",
    "roles": ["analyst"]
  }'
```

Login and capture token:

```bash
ACCESS_TOKEN=$(curl -sS -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"analyst@example.com","password":"strong-password"}' | jq -r '.access_token')
```

Run assessment from local dataset path (development mode only):

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments?dataset_path=data" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Run workflow assessment from local dataset path (development mode only):

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments/workflow" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_path": "data",
    "workflow_context": {
      "workflow_id": "wf_support_triage",
      "name": "Support Triage",
      "business_function": "customer_support",
      "owner": "Head of Support",
      "ai_role": "ticket triage and routing",
      "systems_touched": ["crm", "helpdesk"],
      "human_escalation_path": ["support_lead", "ops_manager"],
      "control_requirements": ["decision_logs", "approval_trace"],
      "blast_radius": "medium",
      "fallback_mode": "manual review queue",
      "override_rights": ["support_manager"],
      "error_tolerance": "low",
      "reversibility": "tickets can be reassigned manually"
    }
  }'
```

Upload assessment via CSV:

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments/upload" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "organizations=@data/organizations.csv" \
  -F "teams=@data/teams.csv" \
  -F "systems=@data/systems.csv" \
  -F "vendors=@data/vendors.csv" \
  -F "facilities=@data/facilities.csv" \
  -F "growth_signals=@data/growth_signals.csv"
```

Upload workflow assessment via CSV:

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments/upload" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F 'workflow_context_json={
    "workflow_id":"wf_support_triage",
    "name":"Support Triage",
    "business_function":"customer_support",
    "owner":"Head of Support",
    "ai_role":"ticket triage and routing",
    "systems_touched":["crm","helpdesk"],
    "human_escalation_path":["support_lead","ops_manager"],
    "control_requirements":["decision_logs","approval_trace"],
    "blast_radius":"medium",
    "fallback_mode":"manual review queue",
    "override_rights":["support_manager"],
    "error_tolerance":"low",
    "reversibility":"tickets can be reassigned manually"
  }' \
  -F "organizations=@data/organizations.csv" \
  -F "teams=@data/teams.csv" \
  -F "systems=@data/systems.csv" \
  -F "vendors=@data/vendors.csv" \
  -F "facilities=@data/facilities.csv" \
  -F "growth_signals=@data/growth_signals.csv"
```

Queue async assessment via CSV:

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments/async/upload" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "organizations=@data/organizations.csv" \
  -F "teams=@data/teams.csv" \
  -F "systems=@data/systems.csv" \
  -F "vendors=@data/vendors.csv" \
  -F "facilities=@data/facilities.csv" \
  -F "growth_signals=@data/growth_signals.csv"
```

Queue async workflow assessment via CSV:

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments/async/upload" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F 'workflow_context_json={
    "workflow_id":"wf_support_triage",
    "name":"Support Triage",
    "business_function":"customer_support",
    "owner":"Head of Support",
    "ai_role":"ticket triage and routing",
    "systems_touched":["crm","helpdesk"],
    "human_escalation_path":["support_lead","ops_manager"],
    "control_requirements":["decision_logs","approval_trace"],
    "blast_radius":"medium",
    "fallback_mode":"manual review queue",
    "override_rights":["support_manager"],
    "error_tolerance":"low",
    "reversibility":"tickets can be reassigned manually"
  }' \
  -F "organizations=@data/organizations.csv" \
  -F "teams=@data/teams.csv" \
  -F "systems=@data/systems.csv" \
  -F "vendors=@data/vendors.csv" \
  -F "facilities=@data/facilities.csv" \
  -F "growth_signals=@data/growth_signals.csv"
```

Poll async job:

```bash
curl -sS "$BASE_URL/api/v1/assessments/async/<job_id>" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Run async load/stress benchmark (1000+ entities):

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_async_benchmark_dataset.py \
  --output-dir .local/performance/datasets/benchmark-1000 \
  --overwrite

ACCESS_TOKEN="$ACCESS_TOKEN" \
PYTHONPATH=src .venv/bin/python scripts/run_async_assessment_benchmark.py \
  --base-url "$BASE_URL" \
  --dataset-dir .local/performance/datasets/benchmark-1000 \
  --jobs 5 \
  --output-dir ".local/performance/benchmarks/$(date -u +%Y%m%dT%H%M%SZ)"
```

Async execution modes:
- `poll` (default): status polling processes at most one queued job per request.
- `background`: API lifespan starts a continuous in-process worker.
- `broker`: API publishes to Redis broker; run `scalescore-worker` for job execution.
- Scheduled dispatch uses `scalescore-worker` in `poll`/`broker` modes and runs in API runtime for `background` mode.

Async job status response includes:
- `progress_stage`
- `progress_percentage` (0-100)
- `progress_message` (best-effort worker message)

Create scheduled assessment via CSV upload:

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments/schedules/upload" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "name=Nightly Org Assessment" \
  -F "cadence=daily" \
  -F "run_hour_utc=3" \
  -F "run_minute_utc=15" \
  -F "organizations=@data/organizations.csv" \
  -F "teams=@data/teams.csv" \
  -F "systems=@data/systems.csv" \
  -F "vendors=@data/vendors.csv" \
  -F "facilities=@data/facilities.csv" \
  -F "growth_signals=@data/growth_signals.csv"
```

Create scheduled workflow assessment via CSV upload:

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments/schedules/upload" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "name=Nightly Support Workflow Assessment" \
  -F "cadence=daily" \
  -F "run_hour_utc=3" \
  -F "run_minute_utc=15" \
  -F 'workflow_context_json={
    "workflow_id":"wf_support_triage",
    "name":"Support Triage",
    "business_function":"customer_support",
    "owner":"Head of Support",
    "ai_role":"ticket triage and routing",
    "systems_touched":["crm","helpdesk"],
    "human_escalation_path":["support_lead","ops_manager"],
    "control_requirements":["decision_logs","approval_trace"],
    "blast_radius":"medium",
    "fallback_mode":"manual review queue",
    "override_rights":["support_manager"],
    "error_tolerance":"low",
    "reversibility":"tickets can be reassigned manually"
  }' \
  -F "organizations=@data/organizations.csv" \
  -F "teams=@data/teams.csv" \
  -F "systems=@data/systems.csv" \
  -F "vendors=@data/vendors.csv" \
  -F "facilities=@data/facilities.csv" \
  -F "growth_signals=@data/growth_signals.csv"
```

List scheduled assessments:

```bash
curl -sS "$BASE_URL/api/v1/assessments/schedules?limit=50&offset=0" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

List assessments:

```bash
curl -sS "$BASE_URL/api/v1/assessments?limit=20&offset=0" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

---

## API Key Example

Create API key:

```bash
curl -sS -X POST "$BASE_URL/api/v1/auth/api-keys" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"automation-key","expires_in_days":90}'
```

Use API key:

```bash
curl -sS "$BASE_URL/api/v1/assessments" \
  -H "X-API-Key: <raw_api_key>"
```

---

## Webhook Example (OpsOrchestra)

```bash
curl -sS -X POST "$BASE_URL/api/v1/webhooks/opsorchestra" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <shared-secret>" \
  -d '{
    "event_type": "entity.updated",
    "tenant_id": "tenant-demo",
    "entity_type": "team",
    "entity_id": "team_ops",
    "entity": {
      "id": "team_ops",
      "type": "team",
      "org_id": "org-demo",
      "name": "Operations",
      "function": "operations",
      "headcount_current": 12
    }
  }'
```

### Outbound Sync Configuration

Set these environment variables to enable outbound assessment sync:

```bash
INTEGRATION_OPSORCHESTRA_OUTBOUND_URL=https://opsorchestra.example.com/api/v1/scalescore/events
INTEGRATION_OPSORCHESTRA_OUTBOUND_TOKEN=<token>
INTEGRATION_OPSORCHESTRA_OUTBOUND_TIMEOUT_SECONDS=10
```

Trigger sync for a report:

```bash
curl -sS -X POST "$BASE_URL/api/v1/assessments/<assessment_id>/sync/opsorchestra" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

### Inbound Graph Pull Configuration

Set these environment variables to enable pull-based entity sync:

```bash
INTEGRATION_OPSORCHESTRA_GRAPH_EXPORT_URL=https://opsorchestra.example.com/api/v1/scalescore/export
INTEGRATION_OPSORCHESTRA_GRAPH_TOKEN=<token>
INTEGRATION_OPSORCHESTRA_GRAPH_TIMEOUT_SECONDS=15
INTEGRATION_OPSORCHESTRA_GRAPH_MAX_ENTITIES_PER_TYPE=5000
INTEGRATION_OPSORCHESTRA_HTTP_MAX_RETRIES=2
INTEGRATION_OPSORCHESTRA_HTTP_RETRY_BACKOFF_SECONDS=0.25
INTEGRATION_OPSORCHESTRA_ALLOW_PRIVATE_NETWORK=false
```

Trigger pull import:

```bash
curl -sS -X POST "$BASE_URL/api/v1/integrations/opsorchestra/pull?org_id=<org_id>" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

---

## Response and Error Shapes

Validation/domain errors generally follow:

```json
{
  "error": {
    "code": "schema_validation_failed",
    "message": "Request validation failed",
    "details": {
      "errors": [
        {
          "field": "body.email",
          "message": "value is not a valid email address",
          "type": "value_error"
        }
      ]
    }
  }
}
```

Some auth handlers use FastAPI `detail` payloads:

```json
{
  "detail": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid email or password"
  }
}
```

---

## OpenAPI Export

Fetch machine-readable schema:

```bash
curl -sS "http://localhost:8000/openapi.json" > openapi.json
```

You can use `openapi.json` for SDK generation or contract testing.
