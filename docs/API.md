# ScaleScore API Reference

> **Last Updated:** February 22, 2026  
> **Version:** v1 (`/api/v1`)

---

## Overview

ScaleScore provides a FastAPI HTTP interface for:
- Authentication and API key management
- Running and retrieving assessments
- Managing organizations and entities
- Importing CSV data
- Receiving OpsOrchestra webhook events

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
cp .env.example .env
uvicorn scalescore.api.main:app --reload
```

Note: `.env.example` sets `AUTH_SKIP_AUTH=true` for development convenience.

---

## Authentication

ScaleScore supports two auth methods:
- `Authorization: Bearer <access_token>`
- `X-API-Key: <api_key>`

Optional integration mode:
- OpsOrchestra-issued Bearer JWTs can be accepted on protected routes when
  `INTEGRATION_OPSORCHESTRA_AUTH_ENABLED=true` and a trusted public key is configured.

### Development bypass

If `AUTH_SKIP_AUTH=true` and `ENVIRONMENT=development`, permission checks use an internal dev admin principal.

For auth integration testing, set:

```bash
AUTH_SKIP_AUTH=false
```

and restart the API.

### Token flow

1. `POST /api/v1/auth/signup`
2. `POST /api/v1/auth/login`
3. Use `access_token` as Bearer token
4. Rotate with `POST /api/v1/auth/refresh`

### OpsOrchestra JWT mode

When enabled, ScaleScore falls back to verifying Bearer tokens with OpsOrchestra settings:

```bash
INTEGRATION_OPSORCHESTRA_AUTH_ENABLED=true
INTEGRATION_OPSORCHESTRA_JWT_PUBLIC_KEY_PATH=/path/to/opsorchestra-public.pem
INTEGRATION_OPSORCHESTRA_JWT_ISSUER=opsorchestra
INTEGRATION_OPSORCHESTRA_JWT_AUDIENCE=scalescore-api
INTEGRATION_OPSORCHESTRA_SUB_CLAIM=sub
INTEGRATION_OPSORCHESTRA_TENANT_CLAIM=tenant_id
INTEGRATION_OPSORCHESTRA_EMAIL_CLAIM=email
INTEGRATION_OPSORCHESTRA_ROLES_CLAIM=roles
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
| `POST` | `/api/v1/assessments/upload` | `assessment:create` | Multipart upload of six CSV files |
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
