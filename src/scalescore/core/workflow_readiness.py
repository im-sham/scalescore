from __future__ import annotations

from collections.abc import Iterable

from scalescore.models.scaling import (
    AssessmentMode,
    CapacityConstraint,
    ConstraintType,
    OrgWorkflowRollup,
    RiskIndicator,
    ScaleScoreReport,
    WorkflowAssessmentContext,
    WorkflowBlastRadius,
    WorkflowPillarScore,
    WorkflowReadinessPillar,
)


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
