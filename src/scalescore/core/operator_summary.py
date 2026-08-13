"""Operator-safe projection of one persisted workflow assessment."""

from datetime import datetime
from math import isfinite
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from scalescore.contracts.assessment_ref import AssessmentRefEnvelope
from scalescore.contracts.workflow_ref import WorkflowRefEnvelope as CanonicalWorkflowRefEnvelope
from scalescore.core.exceptions import ErrorCode, ScaleScoreError
from scalescore.models.scaling import (
    AssessmentMode,
    LegacyWorkflowRefEnvelope,
    ScaleScoreReport,
    WorkflowReadinessPillar,
)


class OperatorPillarSummary(BaseModel):
    """Compact diagnostic summary for one canonical readiness pillar."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    pillar: WorkflowReadinessPillar
    score: float
    grade: str
    rationale: str


class OperatorRemediationAction(BaseModel):
    """Ordered local action without an inferred owner or upstream identity."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: str
    ordinal: int = Field(ge=1)
    action: str


class OperatorReferencePointer(BaseModel):
    """Allowlisted identity and dereference fields from an existing reference."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    ref_id: str
    external_uri: str | None = None
    snapshot_id: str | None = None
    version: str | None = None


class OperatorSummary(BaseModel):
    """Allowlisted workflow diagnostic projection for operator experiences."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    assessment_id: str
    workflow_id: str
    workflow_name: str
    accountable_owner: str | None = None
    readiness_score: float
    readiness_grade: str
    pillars: list[OperatorPillarSummary]
    top_trust_gaps: list[str]
    remediation_actions: list[OperatorRemediationAction]
    source_assessment_generated_at: datetime
    workflow_ref: OperatorReferencePointer | None = None
    assessment_ref: OperatorReferencePointer | None = None
    diagnostic_only: Literal[True] = True
    no_decision_authority: Literal[True] = True


def build_operator_summary(report: ScaleScoreReport) -> OperatorSummary:
    """Build a compact projection only from a complete workflow assessment."""
    context = report.workflow_context
    readiness_score = report.workflow_readiness_score
    readiness_grade = report.workflow_readiness_grade
    canonical_pillars = list(WorkflowReadinessPillar)
    pillar_by_name = {pillar.pillar: pillar for pillar in report.workflow_pillar_scores}
    complete_pillars = (
        len(report.workflow_pillar_scores) == len(canonical_pillars)
        and set(pillar_by_name) == set(canonical_pillars)
        and all(
            _score_is_projectable(pillar.score)
            and bool(pillar.grade.strip())
            and bool(pillar.rationale.strip())
            for pillar in report.workflow_pillar_scores
        )
    )
    complete_identity = bool(
        context is not None and context.workflow_id.strip() and context.name.strip()
    )
    complete_readiness = _score_is_projectable(readiness_score) and bool(
        readiness_grade and readiness_grade.strip()
    )
    complete_diagnostic_items = all(item.strip() for item in report.top_trust_gaps) and all(
        item.strip() for item in report.prioritized_remediation_actions
    )
    aligned_references = context is not None and _references_are_aligned(report)
    if (
        report.assessment_mode != AssessmentMode.WORKFLOW
        or not complete_identity
        or not complete_readiness
        or not complete_pillars
        or not aligned_references
        or not complete_diagnostic_items
    ):
        raise ScaleScoreError(
            message="Assessment is not a complete workflow diagnostic",
            code=ErrorCode.ASSESSMENT_INVALID_STATE,
        )

    if context is None or readiness_score is None or readiness_grade is None:
        raise ScaleScoreError(
            message="Assessment is not a complete workflow diagnostic",
            code=ErrorCode.ASSESSMENT_INVALID_STATE,
        )

    return OperatorSummary(
        assessment_id=report.report_id,
        workflow_id=context.workflow_id,
        workflow_name=context.name,
        accountable_owner=context.owner.strip() or None,
        readiness_score=readiness_score,
        readiness_grade=readiness_grade,
        pillars=[
            OperatorPillarSummary(
                pillar=pillar,
                score=pillar_by_name[pillar].score,
                grade=pillar_by_name[pillar].grade,
                rationale=pillar_by_name[pillar].rationale,
            )
            for pillar in canonical_pillars
        ],
        top_trust_gaps=list(report.top_trust_gaps),
        remediation_actions=[
            OperatorRemediationAction(
                id=f"remediation-{ordinal:02d}",
                ordinal=ordinal,
                action=action,
            )
            for ordinal, action in enumerate(report.prioritized_remediation_actions, start=1)
        ],
        source_assessment_generated_at=report.generated_at,
        workflow_ref=_reference_pointer(report.workflow_ref),
        assessment_ref=_reference_pointer(report.assessment_ref),
    )


def _reference_pointer(
    reference: CanonicalWorkflowRefEnvelope
    | LegacyWorkflowRefEnvelope
    | AssessmentRefEnvelope
    | None,
) -> OperatorReferencePointer | None:
    if reference is None:
        return None
    return OperatorReferencePointer(
        ref_id=reference.ref.ref_id,
        external_uri=reference.ref.external_uri,
        snapshot_id=reference.ref.snapshot_id,
        version=reference.ref.version,
    )


def _score_is_projectable(score: float | None) -> bool:
    return score is not None and isfinite(score) and 0.0 <= score <= 100.0


def _references_are_aligned(report: ScaleScoreReport) -> bool:
    context = report.workflow_context
    if context is None:
        return False

    workflow_ref = report.workflow_ref
    if workflow_ref is not None and (
        workflow_ref.ref.workflow_id != context.workflow_id
        or workflow_ref.ref.organization_id != report.org_id
    ):
        return False

    assessment_ref = report.assessment_ref
    if assessment_ref is None:
        return True
    if workflow_ref is None:
        return False

    assessment = assessment_ref.ref
    nested_workflow = assessment.workflow_ref.ref
    report_workflow = workflow_ref.ref
    return (
        assessment.assessment_type == "workflow_readiness"
        and assessment.assessment_id == report.report_id
        and assessment.organization_id == report.org_id
        and assessment.environment_id == nested_workflow.environment_id
        and nested_workflow.ref_id == report_workflow.ref_id
        and nested_workflow.organization_id == report_workflow.organization_id
        and nested_workflow.environment_id == report_workflow.environment_id
        and nested_workflow.external_uri == report_workflow.external_uri
        and nested_workflow.snapshot_id == report_workflow.snapshot_id
        and nested_workflow.version == report_workflow.version
        and assessment.score == report.workflow_readiness_score
        and assessment.grade == report.workflow_readiness_grade
    )
