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

### `EvidenceRef`

Consumed as source evidence posture for scoring. The current compatibility mapping lands in `WorkflowEvidenceInput`.

### `ControlRef`

Consumed as control coverage and evidence status. The current compatibility mapping lands in `WorkflowControlCoverageInput` and `WorkflowEvidencePostureInput`.

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

## Current Implementation Seams

- `src/scalescore/models/scaling.py` contains workflow, evidence, and Operational Learning suitability models.
- `src/scalescore/core/assessment.py` assembles workflow reports.
- `src/scalescore/core/operational_learning.py` scores suitability.
- `src/scalescore/api/main.py` exposes the current Workflow Context compatibility endpoint at `/api/v1/assessments/mila/workflow`.

## V0.1 Implementation Rule

Preserve `workflow_readiness_score` and the five readiness pillars. Operational Learning remains an optional sibling block. Governance dependency state may block suitability, but Readiness does not approve use.

## Consumer Rules

Workflow Context, Governance, Forge, and Analyst may display `AssessmentRef` summaries. They should dereference the Readiness report when they need full scoring detail.
