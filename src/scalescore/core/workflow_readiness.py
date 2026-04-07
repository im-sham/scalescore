from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from scalescore.models.scaling import (
    AssessmentMode,
    CapacityConstraint,
    ConstraintType,
    OrgWorkflowRollup,
    RiskIndicator,
    ScaleScoreReport,
    WorkflowAssessmentContext,
    WorkflowBlastRadius,
    WorkflowControlCoverageInput,
    WorkflowControlStatus,
    WorkflowEvidenceInput,
    WorkflowEvidencePostureInput,
    WorkflowPillarScore,
    WorkflowReadinessPillar,
)


@dataclass
class _WorkflowEvidenceAdjustment:
    delta: float = 0.0
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    rationale_fragments: list[str] = field(default_factory=list)


def apply_workflow_readiness_context(
    report: ScaleScoreReport,
    workflow_context: WorkflowAssessmentContext,
) -> ScaleScoreReport:
    """Enrich an organization report with workflow-first readiness insights."""

    pillar_scores = _build_workflow_pillar_scores(report, workflow_context)
    workflow_score = round(sum(pillar.score for pillar in pillar_scores) / len(pillar_scores), 1)
    trust_gaps = _collect_top_trust_gaps(pillar_scores, report.top_risks)
    prioritized_actions = _prioritized_actions(report, trust_gaps)
    workflow_grade = _grade_for_score(workflow_score)

    org_rollup = OrgWorkflowRollup(
        org_id=report.org_id,
        workflow_count=1,
        rollup_method="single_workflow_snapshot",
        workflow_ids=[workflow_context.workflow_id],
        report_ids=[report.report_id],
        average_workflow_score=workflow_score,
        overall_grade=workflow_grade,
        lowest_workflow_score=workflow_score,
        highest_workflow_score=workflow_score,
        total_critical_risks=report.critical_risks,
        note=(
            "Single workflow snapshot. Aggregate multiple workflow reports to build an "
            "organization-wide AI operational readiness rollup."
        ),
    )

    return report.model_copy(
        update={
            "assessment_mode": AssessmentMode.WORKFLOW,
            "workflow_context": workflow_context,
            "workflow_readiness_score": workflow_score,
            "workflow_readiness_grade": workflow_grade,
            "workflow_pillar_scores": pillar_scores,
            "top_trust_gaps": trust_gaps,
            "prioritized_remediation_actions": prioritized_actions,
            "org_rollup": org_rollup,
        }
    )


def apply_workflow_evidence_inputs(
    report: ScaleScoreReport,
    workflow_evidence: WorkflowEvidenceInput | None,
) -> ScaleScoreReport:
    """Adjust workflow readiness pillars using structured evidence from direct submissions."""

    if workflow_evidence is None or report.workflow_context is None or not report.workflow_pillar_scores:
        return report

    adjustments = _build_workflow_evidence_adjustments(workflow_evidence)
    adjusted_pillars = [
        _apply_workflow_evidence_adjustment(pillar, adjustments[pillar.pillar])
        for pillar in report.workflow_pillar_scores
    ]
    workflow_score = round(sum(pillar.score for pillar in adjusted_pillars) / len(adjusted_pillars), 1)
    workflow_grade = _grade_for_score(workflow_score)
    trust_gaps = _collect_top_trust_gaps(adjusted_pillars, report.top_risks)
    prioritized_actions = _prioritized_actions(report, trust_gaps)
    org_rollup = (
        report.org_rollup.model_copy(
            update={
                "average_workflow_score": workflow_score,
                "overall_grade": workflow_grade,
                "lowest_workflow_score": workflow_score,
                "highest_workflow_score": workflow_score,
            }
        )
        if report.org_rollup is not None
        else None
    )

    return report.model_copy(
        update={
            "workflow_pillar_scores": adjusted_pillars,
            "workflow_readiness_score": workflow_score,
            "workflow_readiness_grade": workflow_grade,
            "top_trust_gaps": trust_gaps,
            "prioritized_remediation_actions": prioritized_actions,
            "org_rollup": org_rollup,
        }
    )


def derive_org_workflow_rollup(reports: Iterable[ScaleScoreReport]) -> OrgWorkflowRollup:
    """Derive an organization-wide rollup from workflow-first readiness reports."""

    workflow_reports = [report for report in reports if report.workflow_context is not None]
    if not workflow_reports:
        return OrgWorkflowRollup(
            org_id="",
            workflow_count=0,
            average_workflow_score=0.0,
            overall_grade="",
            note="No workflow-scoped reports were provided for rollup.",
        )

    org_id = workflow_reports[0].org_id
    scores = [
        report.workflow_readiness_score
        if report.workflow_readiness_score is not None
        else report.overall_score
        for report in workflow_reports
    ]
    average_score = round(sum(scores) / len(scores), 1)

    return OrgWorkflowRollup(
        org_id=org_id,
        workflow_count=len(workflow_reports),
        rollup_method="mean_workflow_score",
        workflow_ids=[report.workflow_context.workflow_id for report in workflow_reports if report.workflow_context],
        report_ids=[report.report_id for report in workflow_reports],
        average_workflow_score=average_score,
        overall_grade=_grade_for_score(average_score),
        lowest_workflow_score=min(scores),
        highest_workflow_score=max(scores),
        total_critical_risks=sum(report.critical_risks for report in workflow_reports),
        note=(
            "Rollup derived from workflow-scoped readiness reports. Use as an organization-level "
            "view of AI-enabled operational readiness."
        ),
    )


def _build_workflow_pillar_scores(
    report: ScaleScoreReport,
    workflow_context: WorkflowAssessmentContext,
) -> list[WorkflowPillarScore]:
    relevant_constraints = _matching_constraints(report.constraints, workflow_context.systems_touched)
    relevant_risks = _matching_risks(report.top_risks, workflow_context.systems_touched)
    dependency_risks = [
        risk
        for risk in relevant_risks
        if risk.constraint_type == ConstraintType.DEPENDENCY
        or risk.category in {"cascade_risk", "concentration_risk"}
    ]
    governance_risks = [
        risk for risk in relevant_risks if risk.constraint_type == ConstraintType.GOVERNANCE
    ]

    stability_penalty = min(
        55.0,
        report.total_constraints * 5.0
        + report.total_risks * 1.5
        + report.critical_risks * 6.0
        + (8.0 if not workflow_context.reversibility else 0.0),
    )
    resilience_penalty = min(
        55.0,
        len(relevant_constraints) * 8.0
        + len(dependency_risks) * 6.0
        + (12.0 if not workflow_context.systems_touched else 0.0),
    )
    oversight_penalty = (
        (12.0 if not workflow_context.owner else 0.0)
        + (20.0 if not workflow_context.human_escalation_path else 0.0)
        + (15.0 if not workflow_context.fallback_mode else 0.0)
        + (10.0 if not workflow_context.override_rights else 0.0)
        + (5.0 if report.critical_risks else 0.0)
    )
    control_penalty = min(
        50.0,
        (25.0 if not workflow_context.control_requirements else 0.0)
        + (10.0 if len(workflow_context.control_requirements) == 1 else 0.0)
        + len(governance_risks) * 6.0
        + (6.0 if report.critical_risks else 0.0),
    )
    blast_radius_penalty = (
        _blast_radius_penalty(workflow_context.blast_radius)
        + (10.0 if not workflow_context.error_tolerance else 0.0)
        + (10.0 if not workflow_context.reversibility else 0.0)
        + (10.0 if not workflow_context.fallback_mode else 0.0)
    )

    return [
        WorkflowPillarScore(
            pillar=WorkflowReadinessPillar.WORKFLOW_STABILITY,
            score=_bounded_score(report.overall_score + 5.0, stability_penalty),
            grade=_grade_for_score(_bounded_score(report.overall_score + 5.0, stability_penalty)),
            rationale=(
                f"Stability reflects {report.total_constraints} constraints, {report.total_risks} "
                f"known risks, and whether reversibility is documented."
            ),
            strengths=_compact_items(
                [
                    "Baseline operational score is strong enough to support workflow experimentation."
                    if report.overall_score >= 75
                    else None,
                    "Workflow reversibility is documented." if workflow_context.reversibility else None,
                ]
            ),
            gaps=_compact_items(
                [
                    "Operational constraints still need remediation before broader AI scale."
                    if report.total_constraints
                    else None,
                    "Workflow reversibility is not yet documented." if not workflow_context.reversibility else None,
                ]
            ),
        ),
        WorkflowPillarScore(
            pillar=WorkflowReadinessPillar.SYSTEM_AND_DEPENDENCY_RESILIENCE,
            score=_bounded_score(report.overall_score + 2.0, resilience_penalty),
            grade=_grade_for_score(_bounded_score(report.overall_score + 2.0, resilience_penalty)),
            rationale=(
                f"Resilience weighs {len(relevant_constraints)} relevant constraints and "
                f"{len(dependency_risks)} dependency or cascade risks across systems touched."
            ),
            strengths=_compact_items(
                [
                    "Critical systems touched by the workflow are explicitly documented."
                    if workflow_context.systems_touched
                    else None,
                    "No dependency or cascade risks surfaced in the top findings."
                    if not dependency_risks
                    else None,
                ]
            ),
            gaps=_compact_items(
                [
                    "Systems touched by the workflow are not fully documented."
                    if not workflow_context.systems_touched
                    else None,
                    "Dependency concentration or cascade risks could amplify AI workflow failures."
                    if dependency_risks
                    else None,
                ]
            ),
        ),
        WorkflowPillarScore(
            pillar=WorkflowReadinessPillar.HUMAN_OVERSIGHT_AND_OWNERSHIP,
            score=_bounded_score(100.0, oversight_penalty),
            grade=_grade_for_score(_bounded_score(100.0, oversight_penalty)),
            rationale=(
                "Oversight reflects named ownership, documented escalation, override rights, "
                "and fallback behavior."
            ),
            strengths=_compact_items(
                [
                    f"Workflow owner is defined as {workflow_context.owner}." if workflow_context.owner else None,
                    "Human escalation path is documented." if workflow_context.human_escalation_path else None,
                    "Override rights are documented." if workflow_context.override_rights else None,
                ]
            ),
            gaps=_compact_items(
                [
                    "Human escalation path is not documented."
                    if not workflow_context.human_escalation_path
                    else None,
                    "Fallback mode is not documented." if not workflow_context.fallback_mode else None,
                    "Override rights are not explicit." if not workflow_context.override_rights else None,
                ]
            ),
        ),
        WorkflowPillarScore(
            pillar=WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
            score=_bounded_score(100.0, control_penalty),
            grade=_grade_for_score(_bounded_score(100.0, control_penalty)),
            rationale=(
                "Controls reflect approval requirements, evidence expectations, and governance-related "
                "risk signals."
            ),
            strengths=_compact_items(
                [
                    "Control requirements are documented." if workflow_context.control_requirements else None,
                    "No governance-specific top risks surfaced in the current snapshot."
                    if not governance_risks
                    else None,
                ]
            ),
            gaps=_compact_items(
                [
                    "Control requirements are not documented."
                    if not workflow_context.control_requirements
                    else None,
                    "Current findings indicate gaps in control coverage or evidence readiness."
                    if governance_risks or report.critical_risks
                    else None,
                ]
            ),
        ),
        WorkflowPillarScore(
            pillar=WorkflowReadinessPillar.AUTOMATION_FIT_AND_BLAST_RADIUS,
            score=_bounded_score(100.0, blast_radius_penalty),
            grade=_grade_for_score(_bounded_score(100.0, blast_radius_penalty)),
            rationale=(
                f"Automation fit considers blast radius={workflow_context.blast_radius.value}, "
                "fallback coverage, reversibility, and error tolerance."
            ),
            strengths=_compact_items(
                [
                    "Blast radius is limited enough for phased automation."
                    if workflow_context.blast_radius in {WorkflowBlastRadius.LOW, WorkflowBlastRadius.MEDIUM}
                    else None,
                    "Fallback mode is documented." if workflow_context.fallback_mode else None,
                ]
            ),
            gaps=_compact_items(
                [
                    "This workflow has a high blast radius and needs tighter controls before wider AI rollout."
                    if workflow_context.blast_radius in {WorkflowBlastRadius.HIGH, WorkflowBlastRadius.CRITICAL}
                    else None,
                    "Error tolerance is not documented." if not workflow_context.error_tolerance else None,
                    "Fallback mode is not documented." if not workflow_context.fallback_mode else None,
                ]
            ),
        ),
    ]


def _build_workflow_evidence_adjustments(
    workflow_evidence: WorkflowEvidenceInput,
) -> dict[WorkflowReadinessPillar, _WorkflowEvidenceAdjustment]:
    adjustments = {
        pillar: _WorkflowEvidenceAdjustment() for pillar in WorkflowReadinessPillar
    }

    def add(
        pillar: WorkflowReadinessPillar,
        *,
        delta: float = 0.0,
        strength: str | None = None,
        gap: str | None = None,
        rationale: str | None = None,
    ) -> None:
        adjustment = adjustments[pillar]
        adjustment.delta += delta
        if strength:
            adjustment.strengths.append(strength)
        if gap:
            adjustment.gaps.append(gap)
        if rationale:
            adjustment.rationale_fragments.append(rationale)

    if workflow_evidence.owner_confirmed is True:
        add(
            WorkflowReadinessPillar.HUMAN_OVERSIGHT_AND_OWNERSHIP,
            delta=4.0,
            strength="Named workflow ownership is confirmed in source evidence.",
            rationale="Source evidence confirms the named workflow owner.",
        )
    elif workflow_evidence.owner_confirmed is False:
        add(
            WorkflowReadinessPillar.HUMAN_OVERSIGHT_AND_OWNERSHIP,
            delta=-10.0,
            gap="Named workflow ownership is not confirmed in the source evidence.",
            rationale="Source evidence does not confirm the named workflow owner.",
        )

    if workflow_evidence.systems_verified is True:
        add(
            WorkflowReadinessPillar.SYSTEM_AND_DEPENDENCY_RESILIENCE,
            delta=4.0,
            strength="Systems touched are verified in source evidence.",
            rationale="Source evidence confirms the systems touched by this workflow.",
        )
    elif workflow_evidence.systems_verified is False:
        add(
            WorkflowReadinessPillar.SYSTEM_AND_DEPENDENCY_RESILIENCE,
            delta=-8.0,
            gap="Systems touched have not been verified against source evidence.",
            rationale="Source evidence does not verify the systems touched by this workflow.",
        )

    if workflow_evidence.escalation_tested is True:
        add(
            WorkflowReadinessPillar.HUMAN_OVERSIGHT_AND_OWNERSHIP,
            delta=5.0,
            strength="Human escalation path has been tested in source evidence.",
            rationale="Source evidence shows the escalation path has been exercised.",
        )
    elif workflow_evidence.escalation_tested is False:
        add(
            WorkflowReadinessPillar.HUMAN_OVERSIGHT_AND_OWNERSHIP,
            delta=-10.0,
            gap="Human escalation path exists but has not been tested.",
            rationale="Source evidence does not show the escalation path being exercised.",
        )

    if workflow_evidence.fallback_tested is True:
        add(
            WorkflowReadinessPillar.WORKFLOW_STABILITY,
            delta=3.0,
            strength="Fallback mode has been tested in source evidence.",
            rationale="Source evidence confirms the fallback path has been exercised.",
        )
        add(
            WorkflowReadinessPillar.AUTOMATION_FIT_AND_BLAST_RADIUS,
            delta=5.0,
            strength="Fallback mode has been exercised for this workflow.",
            rationale="Source evidence confirms the fallback path can contain failures.",
        )
    elif workflow_evidence.fallback_tested is False:
        add(
            WorkflowReadinessPillar.WORKFLOW_STABILITY,
            delta=-5.0,
            gap="Fallback mode is documented but has not been tested.",
            rationale="Source evidence does not show the documented fallback path being exercised.",
        )
        add(
            WorkflowReadinessPillar.AUTOMATION_FIT_AND_BLAST_RADIUS,
            delta=-7.0,
            gap="Fallback mode has not been tested for blast-radius containment.",
            rationale="Source evidence does not confirm the fallback path can contain failures.",
        )

    if workflow_evidence.override_reviewed is True:
        add(
            WorkflowReadinessPillar.HUMAN_OVERSIGHT_AND_OWNERSHIP,
            delta=3.0,
            strength="Override rights have been reviewed in source evidence.",
            rationale="Source evidence confirms the override path was reviewed.",
        )
    elif workflow_evidence.override_reviewed is False:
        add(
            WorkflowReadinessPillar.HUMAN_OVERSIGHT_AND_OWNERSHIP,
            delta=-6.0,
            gap="Override rights are documented but not confirmed in source evidence.",
            rationale="Source evidence does not confirm the override path.",
        )

    if workflow_evidence.control_coverage is not None:
        _apply_explicit_control_coverage(
            workflow_evidence.control_coverage,
            add=add,
        )

    if workflow_evidence.evidence_posture is not None:
        _apply_explicit_evidence_posture(
            workflow_evidence.evidence_posture,
            add=add,
        )
    elif workflow_evidence.approval_evidence_count is not None:
        if workflow_evidence.approval_evidence_count >= 3:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=6.0,
                strength=(
                    f"{workflow_evidence.approval_evidence_count} approval evidence sample(s) "
                    "were provided."
                ),
                rationale="Approval traceability artifacts were included in the submission.",
            )
        elif workflow_evidence.approval_evidence_count > 0:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=-4.0,
                gap="Approval evidence coverage is still thin for this workflow.",
                rationale="Only limited approval traceability artifacts were provided.",
            )
        else:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=-12.0,
                gap="No approval evidence samples were provided with the workflow submission.",
                rationale="The submission did not include approval traceability artifacts.",
            )

    if workflow_evidence.evidence_posture is None and workflow_evidence.decision_log_count is not None:
        if workflow_evidence.decision_log_count >= 10:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=5.0,
                strength=(
                    f"{workflow_evidence.decision_log_count} decision log sample(s) were provided."
                ),
                rationale="Decision logging samples were included in the submission.",
            )
        elif workflow_evidence.decision_log_count > 0:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=-3.0,
                gap="Decision log sampling is still limited for this workflow.",
                rationale="Only a small number of decision log samples were provided.",
            )
        else:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=-10.0,
                gap="No decision log samples were provided with the workflow submission.",
                rationale="The submission did not include decision logging samples.",
            )

    if workflow_evidence.rollback_tested is True:
        add(
            WorkflowReadinessPillar.WORKFLOW_STABILITY,
            delta=3.0,
            strength="Rollback path has been tested in source evidence.",
            rationale="Source evidence confirms the rollback path has been exercised.",
        )
        add(
            WorkflowReadinessPillar.AUTOMATION_FIT_AND_BLAST_RADIUS,
            delta=6.0,
            strength="Rollback path has been verified for containment.",
            rationale="Source evidence confirms the rollback path can contain failures.",
        )
    elif workflow_evidence.rollback_tested is False:
        add(
            WorkflowReadinessPillar.WORKFLOW_STABILITY,
            delta=-6.0,
            gap="Rollback path has not been tested for this workflow.",
            rationale="Source evidence does not confirm the rollback path was exercised.",
        )
        add(
            WorkflowReadinessPillar.AUTOMATION_FIT_AND_BLAST_RADIUS,
            delta=-10.0,
            gap="Rollback path has not been tested for blast-radius containment.",
            rationale="Source evidence does not confirm rollback containment.",
        )

    return adjustments


def _apply_explicit_control_coverage(
    control_coverage: WorkflowControlCoverageInput,
    *,
    add,
) -> None:
    control_labels = {
        "approval_gate": "Approval gate",
        "decision_logging": "Decision logging",
        "evidence_retention": "Evidence retention",
        "exception_handling": "Exception handling",
        "periodic_review": "Periodic control review",
    }
    status_delta = {
        WorkflowControlStatus.MISSING: -6.0,
        WorkflowControlStatus.DOCUMENTED: -1.5,
        WorkflowControlStatus.OPERATING: 2.5,
        WorkflowControlStatus.VERIFIED: 4.5,
    }

    for field_name, label in control_labels.items():
        status = getattr(control_coverage, field_name)
        if status is None:
            continue

        rationale = f"{label} control is marked as {status.value} in source evidence."
        if status == WorkflowControlStatus.MISSING:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=status_delta[status],
                gap=f"{label} control is missing from the workflow control coverage.",
                rationale=rationale,
            )
        elif status == WorkflowControlStatus.DOCUMENTED:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=status_delta[status],
                gap=f"{label} control is documented but not yet operating.",
                rationale=rationale,
            )
        elif status == WorkflowControlStatus.OPERATING:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=status_delta[status],
                strength=f"{label} control is operating in the workflow.",
                rationale=rationale,
            )
        else:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=status_delta[status],
                strength=f"{label} control is verified by source evidence.",
                rationale=rationale,
            )


def _apply_explicit_evidence_posture(
    evidence_posture: WorkflowEvidencePostureInput,
    *,
    add,
) -> None:
    if evidence_posture.control_evidence_coverage_percent is not None:
        coverage = evidence_posture.control_evidence_coverage_percent
        if coverage >= 90.0:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=6.0,
                strength=f"Control evidence covers {coverage:.1f}% of the mapped workflow controls.",
                rationale="Source evidence coverage for mapped workflow controls is high.",
            )
        elif coverage >= 75.0:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=3.0,
                strength=f"Control evidence covers {coverage:.1f}% of the mapped workflow controls.",
                rationale="Source evidence coverage for mapped workflow controls is adequate.",
            )
        elif coverage >= 50.0:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=-2.0,
                gap=f"Control evidence covers only {coverage:.1f}% of the mapped workflow controls.",
                rationale="Source evidence coverage for mapped workflow controls is only partial.",
            )
        else:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=-8.0,
                gap=f"Control evidence covers only {coverage:.1f}% of the mapped workflow controls.",
                rationale="Source evidence coverage for mapped workflow controls is materially incomplete.",
            )

    if evidence_posture.freshest_evidence_age_days is not None:
        evidence_age = evidence_posture.freshest_evidence_age_days
        if evidence_age <= 30:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=4.0,
                strength=f"Fresh control evidence is {evidence_age} day(s) old.",
                rationale="The freshest control evidence is recent.",
            )
        elif evidence_age <= 90:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=1.0,
                strength=f"Fresh control evidence is {evidence_age} day(s) old.",
                rationale="The freshest control evidence is reasonably current.",
            )
        elif evidence_age <= 180:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=-3.0,
                gap=f"Fresh control evidence is {evidence_age} day(s) old.",
                rationale="The freshest control evidence is aging and should be refreshed.",
            )
        else:
            add(
                WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
                delta=-7.0,
                gap=f"Fresh control evidence is {evidence_age} day(s) old.",
                rationale="The freshest control evidence is stale.",
            )

    if evidence_posture.audit_trail_complete is True:
        add(
            WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
            delta=5.0,
            strength="Audit trail completeness is confirmed in source evidence.",
            rationale="Source evidence confirms the workflow audit trail is complete.",
        )
    elif evidence_posture.audit_trail_complete is False:
        add(
            WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
            delta=-8.0,
            gap="Audit trail completeness is not confirmed for this workflow.",
            rationale="Source evidence does not confirm audit trail completeness.",
        )

    if evidence_posture.linked_artifacts is True:
        add(
            WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
            delta=3.0,
            strength="Workflow evidence includes linked artifacts for reviewer follow-up.",
            rationale="Source evidence includes linked supporting artifacts.",
        )
    elif evidence_posture.linked_artifacts is False:
        add(
            WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS,
            delta=-5.0,
            gap="Workflow evidence does not include linked artifacts for reviewer follow-up.",
            rationale="Source evidence is not linked to supporting artifacts.",
        )


def _apply_workflow_evidence_adjustment(
    pillar: WorkflowPillarScore,
    adjustment: _WorkflowEvidenceAdjustment,
) -> WorkflowPillarScore:
    score = round(max(0.0, min(100.0, pillar.score + adjustment.delta)), 1)
    strengths = _dedupe_compact_items([*pillar.strengths, *adjustment.strengths])[:5]
    gaps = _dedupe_compact_items([*pillar.gaps, *adjustment.gaps])[:5]
    rationale = pillar.rationale
    if adjustment.rationale_fragments:
        rationale = f"{pillar.rationale} {' '.join(adjustment.rationale_fragments)}".strip()
    return pillar.model_copy(
        update={
            "score": score,
            "grade": _grade_for_score(score),
            "strengths": strengths,
            "gaps": gaps,
            "rationale": rationale,
        }
    )


def _matching_constraints(
    constraints: list[CapacityConstraint],
    systems_touched: list[str],
) -> list[CapacityConstraint]:
    normalized = _normalize_values(systems_touched)
    if not normalized:
        return [
            constraint
            for constraint in constraints
            if constraint.entity_type in {"system", "vendor", "facility"}
        ]
    return [
        constraint
        for constraint in constraints
        if constraint.entity_id.casefold() in normalized
        or constraint.entity_name.casefold() in normalized
    ]


def _matching_risks(
    risks: list[RiskIndicator],
    systems_touched: list[str],
) -> list[RiskIndicator]:
    normalized = _normalize_values(systems_touched)
    if not normalized:
        return list(risks)
    return [
        risk
        for risk in risks
        if any(entity.casefold() in normalized for entity in risk.affected_entities)
        or risk.category in {"cascade_risk", "concentration_risk"}
    ]


def _collect_top_trust_gaps(
    pillar_scores: list[WorkflowPillarScore],
    risks: list[RiskIndicator],
) -> list[str]:
    ranked_gaps: list[str] = []
    for pillar in sorted(pillar_scores, key=lambda score: score.score):
        ranked_gaps.extend(pillar.gaps)
    ranked_gaps.extend(
        f"Critical risk: {risk.title}"
        for risk in risks
        if risk.risk_level.value in {"critical", "high"}
    )

    deduped = list(dict.fromkeys(gap for gap in ranked_gaps if gap))
    return deduped[:5]


def _prioritized_actions(report: ScaleScoreReport, trust_gaps: list[str]) -> list[str]:
    actions = [recommendation.title for recommendation in report.recommendations[:5]]
    if actions:
        return actions

    fallback_actions = [
        "Document the human escalation path and fallback mode for this workflow."
        if any("escalation" in gap.lower() or "fallback" in gap.lower() for gap in trust_gaps)
        else None,
        "Define control requirements and evidence expectations before expanding automation."
        if any("control" in gap.lower() or "evidence" in gap.lower() for gap in trust_gaps)
        else None,
        "Reduce dependency concentration or add redundancy for critical workflow systems."
        if any("dependency" in gap.lower() or "blast radius" in gap.lower() for gap in trust_gaps)
        else None,
    ]
    compact = _compact_items(fallback_actions)
    return compact[:3] or ["Prioritize remediation for the highest-impact workflow trust gap."]


def _blast_radius_penalty(blast_radius: WorkflowBlastRadius) -> float:
    penalties = {
        WorkflowBlastRadius.LOW: 5.0,
        WorkflowBlastRadius.MEDIUM: 12.0,
        WorkflowBlastRadius.HIGH: 22.0,
        WorkflowBlastRadius.CRITICAL: 30.0,
    }
    return penalties[blast_radius]


def _bounded_score(base_score: float, penalty: float) -> float:
    return round(max(0.0, min(100.0, base_score - penalty)), 1)


def _grade_for_score(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _normalize_values(values: list[str]) -> set[str]:
    return {value.strip().casefold() for value in values if value.strip()}


def _compact_items(values: list[str | None]) -> list[str]:
    return [value for value in values if value]


def _dedupe_compact_items(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(_compact_items(values)))
