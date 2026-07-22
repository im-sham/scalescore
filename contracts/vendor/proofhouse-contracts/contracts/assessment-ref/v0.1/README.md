# AssessmentRef V0.1

`AssessmentRef` is a private, neutral-distribution contract family. This repository owns distribution mechanics only; Readiness owns semantics and sensitivity. A valid diagnostic status is never Governance approval, a policy decision, a use approval, release authority, or use authority.

## Authority sources

- Accepted D-12 protected-main decision: USMI `e401def7f42e66691d2552272b67501b5b5df04a`, `decisions/2026-07-17-wp-ri-03-assessment-ref-d12-owner-acceptance.md`.
- Current protected-main Readiness product canon: ScaleScore / Readiness `5ed3a0f1c0a4d28e154852df4fa402c55b7b7cdc`, `src/scalescore/models/scaling.py` and `src/scalescore/core/assessment.py`.

## Canonical field mapping

| Contract surface | Source | Bounded interpretation |
| --- | --- | --- |
| `contract_version`, `contract_name`, `producer_capability`, `producer_system`, `canonical_owner`, `issued_at`, `cache_policy`, `ref` | Readiness `models/scaling.py`, `AssessmentRefEnvelope` | Existing protected-main envelope fields. D-12 fixes Readiness ownership, ScaleScore / Readiness as sole initial producer, and `summary_snapshot` as the only cache policy. |
| `ref_id`, `ref_type`, `source_capability`, `organization_id`, `environment_id`, `external_uri`, `snapshot_id`, `version`, `created_at`, `summary`, `assessment_id` | Readiness `models/scaling.py`, `AssessmentRef`; construction in `core/assessment.py::apply_assessment_ref` | Existing protected-main reference metadata. `organization_id` is the existing tenant-scoping identifier; `external_uri` is only a reference to the authenticated, tenant-scoped Readiness detail interface. Required `snapshot_id` and `version` make integrity/version identity fail closed without defining new digest semantics. Fixture URI and identifiers are synthetic test values, not canonical endpoint or tenant claims. |
| `workflow_ref` outer fields: `contract_version`, `contract_name`, `producer_capability`, `producer_system`, `canonical_owner`, `issued_at`, `cache_policy`, `ref` | Readiness `models/scaling.py`, `WorkflowRefEnvelope`; D-12 embedded-`WorkflowRef` boundary | Existing protected-main WorkflowRef envelope metadata. The schema intentionally excludes workflow title, subject, owner, review status, summaries, and other workflow truth. Workflow Context remains canonical and is the dereference owner. |
| `workflow_ref.ref` fields: `ref_id`, `ref_type`, `source_capability`, `organization_id`, `environment_id`, `external_uri`, `snapshot_id`, `version` | Readiness `models/scaling.py`, `WorkflowRef` | Existing protected-main reference fields only. `workflow_ref.ref.organization_id` must equal the containing AssessmentRef `organization_id`; this fail-closed tenant invariant does not transfer Workflow Context semantic ownership. |
| `assessment_type` values `workflow_readiness`, `operational_learning_suitability` | Readiness `models/scaling.py`, `AssessmentRef.assessment_type` | Existing protected-main Readiness diagnostic types. The operational-learning-related type does not make Operational Learning a consumer: D-12 explicitly excludes OL initial adoption. |
| `score` and bounds `0..100` | Readiness scoring fields use the `0..100` scale; D-12 identifies permissive score handling as a defect; the accepted implementation instruction requires fail-closed bounds | Diagnostic score only. It is not approval or permission to act. |
| `grade` values `A`, `B`, `C`, `D`, `F` | Readiness `core/assessment.py::_grade_for_score` | Deterministic protected mapping: `A` for score `>=90`, `B` for `>=80`, `C` for `>=70`, `D` for `>=60`, otherwise `F`. |
| `status` values `ready`, `watch`, `at_risk`, `blocked` | Readiness `core/assessment.py::_assessment_ref_status`; D-12 diagnostic-only status semantics | Deterministic protected mapping: `ready` for score `>=80`, `watch` for `>=65`, `at_risk` for `>=50`, otherwise `blocked`. None is a Governance or use decision. |
| `top_blockers`, `top_reasons`, maximum five entries | Readiness `models/scaling.py`, `AssessmentRef`; `core/assessment.py::_assessment_ref_top_blockers` and `_assessment_ref_top_reasons` | Existing protected-main bounded diagnostic summaries. They may not carry full reports, pillar detail, raw/customer/source payloads, credentials, or Governance truth. |
| `schema.json` closed objects and required fields | D-12 drift disposition and authorized schema/conformance work | `additionalProperties: false` and required identity, tenant scope, version, and snapshot identity remediate accepted permissive/unknown-field drift. Draft 2020-12 constraints enforce score-to-grade and score-to-status mappings; generated/runtime semantic validators enforce workflow tenant equality because standard JSON Schema cannot compare values at two instance paths. |

## Access and payload boundary

Only reference metadata and the bounded diagnostic summary may be cached. Full reports remain behind the authenticated, tenant-scoped Readiness dereference. The family excludes full scoring reports, readiness pillar details, raw/source/customer payloads, credentials, and canonical Governance policy, approval, or use-authority truth.
