# Staging Validation Runbook

> **Last Updated:** February 24, 2026  
> **Purpose:** Validate v0.7 OpsOrchestra integration hardening and v0.8 async slice before release promotions.

---

## Preconditions

1. `ENVIRONMENT=staging`
2. `AUTH_SKIP_AUTH=false`
3. Valid auth store initialized (at least one admin or service principal)
4. Integration settings configured:
```bash
INTEGRATION_OPSORCHESTRA_AUTH_ENABLED=true
INTEGRATION_OPSORCHESTRA_JWKS_URL=https://<opsorchestra-host>/.well-known/jwks.json
INTEGRATION_OPSORCHESTRA_GRAPH_EXPORT_URL=https://<opsorchestra-host>/api/v1/scalescore/export
INTEGRATION_OPSORCHESTRA_OUTBOUND_URL=https://<opsorchestra-host>/api/v1/scalescore/events
INTEGRATION_OPSORCHESTRA_WEBHOOK_SECRET=<shared-secret>
FEATURE_ENABLE_ASYNC_ASSESSMENTS=true
# Optional when validating broker mode:
# ASYNC_ASSESSMENT_MODE=broker
# ASYNC_ASSESSMENT_BROKER_URL=rediss://<redis-host>:6379/0
# ASYNC_ASSESSMENT_BROKER_QUEUE_NAME=scalescore:async-assessment:jobs
# ASYNC_ASSESSMENT_BROKER_RESERVATION_TIMEOUT_SECONDS=300
FEATURE_ENABLE_SCHEDULED_ASSESSMENTS=true
```

---

## Automated Validation

Run core hardening and API regression checks:

```bash
./scripts/collect_staging_validation_evidence.sh
```

or run checks manually:

```bash
PYTHONPATH=src .venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/pytest -q
PYTHONPATH=src .venv/bin/pip-audit --progress-spinner off
```

Expected:
- lint clean
- all tests passing
- no known vulnerable dependencies

### CI automation (recommended)

The release-gate workflow is automated in:

- `.github/workflows/staging-validation-gate.yml`

It runs on:
- manual dispatch (`workflow_dispatch`)
- weekly schedule (Monday 09:00 UTC)

Workflow outputs:
- async benchmark artifacts (`benchmark_results.json`, `benchmark_summary.md`)
- release-gate evaluation artifacts (`release_gate_result.json`, `release_gate_summary.md`)
- auth smoke evidence (internal JWT and external OIDC)

Notes:
- The workflow generates ephemeral internal JWT signing keys at runtime so `ENVIRONMENT=staging` auth flows can be exercised without checking secrets into the repo.
- External OIDC smoke uses a separate ephemeral RSA keypair and uploads only the smoke results, not the private keys.

---

## Async Load/Stress Validation (1000+ Entities)

Use these benchmark artifacts to validate v0.8 async queue behavior at scale.

1. Generate a large, schema-valid dataset:
```bash
PYTHONPATH=src .venv/bin/python scripts/generate_async_benchmark_dataset.py \
  --output-dir .local/performance/datasets/staging-1000 \
  --organizations 1 \
  --teams-per-org 300 \
  --systems-per-org 300 \
  --vendors-per-org 300 \
  --facilities-per-org 300 \
  --growth-signals-per-org 40 \
  --overwrite
```
2. Execute async benchmark against staging:
```bash
ACCESS_TOKEN=<analyst-token> \
PYTHONPATH=src .venv/bin/python scripts/run_async_assessment_benchmark.py \
  --base-url "$BASE_URL" \
  --dataset-dir .local/performance/datasets/staging-1000 \
  --jobs 5 \
  --poll-interval-seconds 0.5 \
  --timeout-seconds 1800 \
  --output-dir ".local/performance/benchmarks/staging-$(date -u +%Y%m%dT%H%M%SZ)"
```
3. Review generated artifacts:
- `benchmark_results.json` (machine-readable job traces + metrics)
- `benchmark_summary.md` (release-note friendly summary)
- `release_gate_result.json` (machine-readable pass/fail per criterion)
- `release_gate_summary.md` (final release-gate decision and rationale)

Notes:
- If staging runs with `AUTH_SKIP_AUTH=true`, omit `ACCESS_TOKEN`.
- For `ASYNC_ASSESSMENT_MODE=broker`, ensure `scalescore-worker` is running.

Release gate checks:
- `completed_jobs == submitted_jobs`
- `failed_jobs == 0`
- `timed_out_jobs == 0`
- `completion_latency_seconds.p95` captured and compared against prior baseline (investigate >25% regression)

---

## Staging Smoke Checklist

## 1) OpsOrchestra JWT trust path

1. Issue an OpsOrchestra token with expected issuer/audience/claims.
2. Call protected endpoint:
```bash
curl -i "$BASE_URL/api/v1/assessments" \
  -H "Authorization: Bearer <opsorchestra-token>"
```
Expected: `200` (or empty list if no reports).

## 2) Graph pull import

```bash
curl -i -X POST "$BASE_URL/api/v1/integrations/opsorchestra/pull" \
  -H "Authorization: Bearer <admin-token>"
```
Expected:
- `200`
- payload includes `status=imported`, `imported_total`, `imported_counts`

## 3) Outbound sync

1. Create an assessment.
2. Trigger sync:
```bash
curl -i -X POST "$BASE_URL/api/v1/assessments/<assessment_id>/sync/opsorchestra" \
  -H "Authorization: Bearer <admin-token>"
```
Expected:
- `200`
- payload includes `status=synced`

## 4) Webhook ingestion

```bash
curl -i -X POST "$BASE_URL/api/v1/webhooks/opsorchestra" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <shared-secret>" \
  -d '{"event_type":"entity.updated","tenant_id":"<tenant>","entity_type":"team","entity_id":"team-x","entity":{"id":"team-x","org_id":"org-1","name":"Ops","function":"operations","headcount_current":8}}'
```
Expected: `200` and `action=upserted`.

## 5) Async assessment slice

1. Submit async upload:
```bash
curl -i -X POST "$BASE_URL/api/v1/assessments/async/upload" \
  -H "Authorization: Bearer <analyst-token>" \
  -F "organizations=@data/organizations.csv" \
  -F "teams=@data/teams.csv" \
  -F "systems=@data/systems.csv" \
  -F "vendors=@data/vendors.csv" \
  -F "facilities=@data/facilities.csv" \
  -F "growth_signals=@data/growth_signals.csv"
```
2. Poll status:
```bash
curl -i "$BASE_URL/api/v1/assessments/async/<job_id>" \
  -H "Authorization: Bearer <analyst-token>"
```

Mode-specific notes:
- `ASYNC_ASSESSMENT_MODE=poll`: polling endpoint advances queued jobs.
- `ASYNC_ASSESSMENT_MODE=background`: API process runs local worker loop.
- `ASYNC_ASSESSMENT_MODE=broker`: run worker process in staging:
```bash
scalescore-worker
```

Expected:
- initial `status=queued|processing`
- eventual `status=completed` with `report_id`

## 6) Scheduled assessment dispatch

1. Create a schedule:
```bash
curl -i -X POST "$BASE_URL/api/v1/assessments/schedules/upload" \
  -H "Authorization: Bearer <analyst-token>" \
  -F "name=Staging Daily Assessment" \
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
2. Verify schedule exists:
```bash
curl -i "$BASE_URL/api/v1/assessments/schedules" \
  -H "Authorization: Bearer <analyst-token>"
```
3. Verify a worker is running (`scalescore-worker` for broker/poll modes or API background mode).

Expected:
- schedule state is `active`
- `next_run_at` is populated
- after due time, `last_job_id` is populated and linked async job completes

---

## Exit Criteria

- All automated checks pass
- All six smoke checks pass
- No unresolved `5xx` responses in staging logs for tested flows
- Audit evidence links recorded in release notes
