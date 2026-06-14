# Agent Guide

This repo implements Proofhouse Readiness through the current `scalescore`
technical service. Read this before changing code or docs.

## Naming

- Use `Proofhouse Readiness` or `Readiness` in product, roadmap, and
  customer-facing language.
- Keep `scalescore` for package imports, CLI commands, env vars, auth claims,
  API routes, worker names, and repository references until a dedicated rename
  wave changes those identifiers.
- `ScaleScore` is acceptable for the current technical service, historical docs,
  compatibility-mode behavior, and concrete classes such as `ScaleScoreReport`.

## Product Boundary

Readiness owns workflow scoring and diagnostics:

- workflow readiness score and five readiness pillars
- trust-gap diagnosis and remediation prioritization
- organization rollups derived from workflow assessments
- Operational Learning suitability scoring as a sibling lens
- compact `AssessmentRef` summaries for downstream Proofhouse consumers

Readiness does not own canonical workflow truth, rights approval, redaction
review, export eligibility, promotion approval, asset derivation, or incident
memory.

Suite boundaries:

- Workflow Context owns canonical workflow records, snapshots, evidence linkage,
  and operational context.
- Governance owns rights, policy, redaction review, use approval, export control,
  manifests, and audit-grade use control.
- Operational Learning owns derivation/package work and promotion state.
- Forge owns incident memory and failure-pattern learning.

Operational Learning suitability states from this repo are diagnostics only.
They never approve internal eval use, internal training use, promotion, export,
or residual-risk acceptance.

## Implementation Seams

- `src/scalescore/api/main.py` defines the FastAPI app and current assessment
  endpoints, including Workflow Context compatibility routes.
- `src/scalescore/core/assessment.py` assembles workflow reports.
- `src/scalescore/core/workflow_readiness.py` applies readiness enrichment.
- `src/scalescore/core/operational_learning.py` scores Operational Learning
  suitability.
- `src/scalescore/core/document_operations.py` derives local Readiness
  projections from the document-operations fixture.
- `src/scalescore/models/scaling.py` contains workflow, evidence, assessment,
  and suitability models.
- `src/scalescore/storage/*_repository.py` owns persistence behavior.
- `src/scalescore/core/async_assessment.py`, `src/scalescore/core/async_broker.py`,
  `src/scalescore/core/scheduled_assessment.py`, and `src/scalescore/worker.py`
  own async, broker, scheduled, and worker flows.
- `src/scalescore/connectors/opsorchestra_connector.py` emits compact outbound
  summaries only; do not send raw workflow findings, notes, source documents, or
  full report exports through this connector.

## Data Handling

- Treat direct `source_findings`, `notes`, and document-operations profile
  identifiers as summary/ref-only fields.
- Preserve guards that reject raw payload-shaped JSON and sensitive/raw payload
  keys before persistence.
- Keep tenant scoping on repository reads and writes.
- Keep auth and staging guards fail-closed for production/staging settings.
- Do not make Readiness persist or mutate upstream Workflow Context,
  Governance, Operational Learning, or Forge truth.

## Development Workflow

- Prefer small PRs scoped to one behavioral contract.
- Add or update tests before changing implementation behavior.
- Preserve org-level compatibility while adding workflow-first behavior.
- Do not rename package/runtime identifiers as part of unrelated work.
- Keep generated caches, local databases, reports, and credentials out of git.

Useful local commands:

```bash
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
```

Use the project virtualenv when available. In this workspace that is usually:

```bash
/Users/shamimrehman/Projects/scalescore/.venv/bin/python -m pytest
```

For PRs that touch async, broker, scheduled assessment, or storage behavior,
run the relevant unit tests and at least the API e2e tests. For security,
auth, tenant isolation, raw-payload rejection, or outbound connector changes,
run the full suite.
