# Proofhouse Readiness Contract Guide

**Status:** Active local guide  
**Suite contract:** `proofhouse-shared-contracts/v0.1`

This repo implements Proofhouse Readiness through the current `scalescore` technical service. Readiness scores workflows and emits assessment truth. It does not own workflow truth or use approvals.

## Canonical Ownership

Readiness owns:

- workflow readiness score
- five workflow-readiness pillars
- trust gaps
- prioritized remediation actions
- organization rollups derived from workflow assessments
- Operational Learning suitability scoring as a sibling lens

Readiness does not own:

- Workflow Context canonical records or snapshots
- Governance rights, redaction review, use approval, export eligibility, or manifests
- Forge incident-memory truth
- Operational Learning asset derivation or promotion state

## Shared Refs This Repo Should Consume

### `WorkflowRef`

Consumed as workflow context for assessment. The current compatibility mapping lands in `WorkflowAssessmentContext`.

Current implementation:

- `CreateMilaWorkflowAssessmentRequest.workflow_ref` accepts the V0.1 `WorkflowRef` envelope.
- `ScaleScoreReport.workflow_ref` preserves and echoes the upstream canonical Workflow Context ref.
- `workflow_context` remains the scoring compatibility payload and is not replaced by `workflow_ref`.

### `EvidenceRef`

Consumed as source evidence posture for scoring. The current compatibility mapping lands in `WorkflowEvidenceInput`.

### `ControlRef`

Workflow Context is the semantic owner, sensitivity authority, and sole initial
producer. Readiness is a consumer only. Canonical control detail is available
only by authenticated, tenant-scoped dereference through Workflow Context;
Readiness never reconstructs canonical detail from the shared metadata.

Current implementation:

- `CreateMilaWorkflowAssessmentRequest.control_refs` validates the generated,
  byte-pinned V0.1 `ControlRef` binding at Contracts commit
  `299384b1432fe4071d0d43ae4710e81feb9e31a5`.
- Request `org_id`, authenticated tenant, `workflow_context.workflow_id`,
  optional top-level `WorkflowRef`, every `ControlRef`, and every embedded
  owning `WorkflowRef` must align across tenant, environment, and workflow
  before scoring or persistence.
- `ScaleScoreReport.control_refs`, SQLite persistence/readback, and API
  responses preserve canonical field values and the producer's immutable-pin
  omission shape. Explicit JSON null pins are invalid; an omitted alternate pin
  remains valid.
- `implementation_state` and `linkage_state` feed conservative Readiness
  diagnostics only. They do not imply owner confirmation, Governance approval,
  policy or use authority, release or external authority, gate state, or
  completion. Verified linkage is not counted as approval evidence, a decision
  log, or a complete audit trail.
- Synthetic canonical placeholders use `planned` / `missing` and state that no
  durable Workflow assignment record exists. They may claim stronger states
  only when backed by a real immutable Workflow assignment.

One-release compatibility is deliberately narrow: the exact former
repository-local envelope/ref shape remains accepted inbound because the
existing Workflow Context compatibility route is a live product path, and it
remains readable from stored reports. Legacy objects remain observably legacy;
they are never repaired or converted into canonical `ControlRef` truth, and
authority-like legacy fields are not scored. Historical Pydantic behavior is
retained: omitted legacy fields with defaults are accepted and those defaults
materialize during serialization and persistence/readback.
Malformed canonical input cannot enter through the legacy branch. Removal is a
release-boundary migration, not part of WP-RI-03.

This migration excludes `PolicyDecisionRef`, `UseApprovalRef`, deployment,
release activation, live data, Operational Learning activation, external use,
and WP-RI-03/G3 closure.

### Document-operations profile

Consumed as a local Readiness projection of Workflow Context snapshot signals for the flagship document-operations fixture. It is not a new shared contract object and it does not store editable workflow truth.

Current implementation:

- `CreateMilaWorkflowAssessmentRequest.document_operations_profile` accepts the document-operations summary profile for `document_ops_regulated_review_v0`.
- `src/scalescore/core/document_operations.py` derives local `WorkflowEvidenceInput` and `OperationalLearningInputs` when more explicit inputs are not supplied.
- The profile can represent the normal packet, escalated exception packet, evidence posture, review density, and Governance dependency state needed for suitability scoring.
- The profile can optionally include a synthetic claims `claims_profile` block for `claims-hybrid-high-dollar-review-v0`; Readiness consumes it only to score claims suitability and trust gaps.

## Shared Refs This Repo Should Emit

### `AssessmentRef`

Readiness should emit a compact assessment reference instead of requiring downstream consumers to copy full reports.

Minimum V0.1 projection:

- `assessment_id` from `ScaleScoreReport.report_id`
- `workflow_ref` from `ScaleScoreReport.workflow_context`
- `assessment_type`: `workflow_readiness` or `operational_learning_suitability`
- `score`
- `grade`
- `status`
- `top_blockers`
- `top_reasons`
- `report_uri` when available

Current implementation:

- `ScaleScoreReport.assessment_ref` emits the V0.1 `AssessmentRef` envelope for workflow reports.
- `AssessmentRef.workflow_ref` carries the upstream `WorkflowRef` envelope when Workflow Context supplies one.
- `AssessmentRef.workflow_id` remains as a compatibility field when a caller only supplies `workflow_context`.
- Document-operations reports use the same `AssessmentRef` projection; downstream consumers should dereference the report for full pillar and Operational Learning details.

## Current Implementation Seams

- `src/scalescore/models/scaling.py` contains workflow, evidence, and Operational Learning suitability models.
- `src/scalescore/core/assessment.py` assembles workflow reports.
- `src/scalescore/core/operational_learning.py` scores suitability.
- `src/scalescore/api/main.py` exposes the current Workflow Context compatibility endpoint at `/api/v1/assessments/mila/workflow`.
- Direct workflow `source_findings`, `notes`, and document-operations profile identifiers are summary/ref-only fields. The compatibility endpoint rejects obvious raw payload-shaped JSON or sensitive/raw payload keys before creating or storing a report.
- OpsOrchestra outbound sync sends compact workflow readiness, claims suitability, and Operational Learning suitability summaries only. It does not send direct workflow `source_findings`, direct `notes`, source documents, or full report exports.

## V0.1 Implementation Rule

Preserve `workflow_readiness_score` and the five readiness pillars. Operational Learning remains an optional sibling block. Governance dependency state may block suitability, but Readiness does not approve use.

For document operations, Readiness may say a workflow is a `weak_candidate`, `eval_suitable`, `training_candidate`, `blocked`, or `unsuitable`. These are suitability states only; internal-eval use still requires Governance approval.

For claims suitability, Readiness may say the synthetic claims workflow is `blocked`, `weak_candidate`, or `eval_suitable` based on PHI/redaction posture, rate-source traceability, downstream consistency/action readiness, savings lifecycle, Governance dependency state, source readiness, and evidence-class coverage. These are trust-gap diagnostics only; Governance remains the approval source for use approvals, redaction review, export control, action approval, durable decisions, and audit readback.

## Consumer Rules

Workflow Context, Governance, Forge, and Analyst may display `AssessmentRef` summaries. They should dereference the Readiness report when they need full scoring detail.
