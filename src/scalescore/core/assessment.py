from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scalescore.connectors.csv_connector import CSVConnector
from scalescore.core.document_operations import derive_document_operations_readiness_inputs
from scalescore.core.exceptions import (
    MultipleOrganizationsError,
    OrganizationRequiredError,
)
from scalescore.core.operational_learning import apply_operational_learning_inputs
from scalescore.core.reporting import generate_executive_summary
from scalescore.core.workflow_readiness import (
    apply_workflow_evidence_inputs,
    apply_workflow_readiness_context,
)
from scalescore.models.core import Facility, Organization, System, Team, Vendor
from scalescore.models.scaling import (
    AssessmentMode,
    AssessmentRef,
    AssessmentRefEnvelope,
    CapacityConstraint,
    DocumentOperationsReadinessProfile,
    FunctionalArea,
    OperationalLearningInputs,
    RiskIndicator,
    RiskLevel,
    ScaleScoreReport,
    WorkflowAssessmentContext,
    WorkflowBlastRadius,
    WorkflowControlCoverageInput,
    WorkflowEvidenceInput,
    WorkflowEvidencePostureInput,
    WorkflowRefEnvelope,
)
from scalescore.scoring.bottleneck_detector import BottleneckDetector
from scalescore.scoring.engine import ScoringConfig, ScoringEngine
from scalescore.scoring.recommender import RecommendationEngine


def run_assessment_from_csv(
    directory: str | Path,
    workflow_context: WorkflowAssessmentContext | None = None,
) -> ScaleScoreReport:
    connector = CSVConnector()
    data = connector.load_all(directory)
    return run_assessment(
        organizations=data["organizations"],
        teams=data["teams"],
        systems=data["systems"],
        vendors=data["vendors"],
        facilities=data["facilities"],
        growth_signals=data["growth_signals"],
        workflow_context=workflow_context,
    )


def run_assessment(
    *,
    organizations: list[Organization],
    teams: list[Team] | None = None,
    systems: list[System],
    vendors: list[Vendor] | None = None,
    facilities: list[Facility],
    growth_signals: list,
    workflow_context: WorkflowAssessmentContext | None = None,
) -> ScaleScoreReport:
    if not organizations:
        raise OrganizationRequiredError()

    org_ids = {org.id for org in organizations}
    if len(org_ids) > 1:
        raise MultipleOrganizationsError(count=len(org_ids))

    organization = organizations[0]
    teams = teams or []
    vendors = vendors or []

    detector = BottleneckDetector()
    constraints, risks = detector.detect_bottlenecks(
        org_id=organization.id,
        systems=systems,
        facilities=facilities,
        vendors=vendors,
        growth_signals=growth_signals,
    )

    constraint_by_area: dict[FunctionalArea, list[CapacityConstraint]] = {
        area: [] for area in FunctionalArea
    }
    for constraint in constraints:
        area = _constraint_area(constraint)
        constraint_by_area[area].append(constraint)

    risk_by_area: dict[FunctionalArea, list[RiskIndicator]] = {area: [] for area in FunctionalArea}
    for risk in risks:
        risk_by_area[risk.functional_area].append(risk)

    areas = _assessment_areas(constraint_by_area, risk_by_area, growth_signals)
    engine = ScoringEngine(config=ScoringConfig.from_settings())
    area_scores = [
        engine.calculate_area_score(
            org_id=organization.id,
            area=area,
            constraints=constraint_by_area.get(area, []),
            risks=risk_by_area.get(area, []),
            growth_signals=growth_signals,
        )
        for area in areas
    ]

    overall_score = (
        round(sum(score.score for score in area_scores) / len(area_scores), 1)
        if area_scores
        else 0.0
    )

    recommender = RecommendationEngine()
    recommendations = recommender.generate_recommendations(
        org_id=organization.id,
        constraints=constraints,
        risks=risks,
    )

    top_risks = sorted(risks, key=lambda r: r.risk_score, reverse=True)[:5]
    critical_risks = sum(1 for r in risks if r.risk_level == RiskLevel.CRITICAL)
    high_risks = sum(1 for r in risks if r.risk_level == RiskLevel.HIGH)

    report = ScaleScoreReport(
        report_id=str(uuid4()),
        org_id=organization.id,
        org_name=organization.name,
        generated_at=datetime.now(UTC),
        overall_score=overall_score,
        overall_grade=_grade_for_score(overall_score),
        overall_trend=_overall_trend(area_scores),
        area_scores=area_scores,
        top_risks=top_risks,
        constraints=constraints,
        recommendations=recommendations,
        growth_signals=growth_signals,
        total_risks=len(risks),
        critical_risks=critical_risks,
        high_risks=high_risks,
        total_constraints=len(constraints),
        total_recommendations=len(recommendations),
        executive_summary="",
        key_findings=_generate_key_findings(constraints, risks),
        immediate_actions=_generate_immediate_actions(recommendations),
    )
    if workflow_context is not None:
        report = apply_workflow_readiness_context(report, workflow_context)
    report.executive_summary = generate_executive_summary(report)
    report = apply_assessment_ref(report)

    return report


def run_workflow_assessment(
    *,
    org_id: str,
    org_name: str,
    workflow_context: WorkflowAssessmentContext,
    workflow_ref: WorkflowRefEnvelope | None = None,
    baseline_operational_score: float | None = None,
    workflow_evidence: WorkflowEvidenceInput | None = None,
    operational_learning_inputs: OperationalLearningInputs | None = None,
    document_operations_profile: DocumentOperationsReadinessProfile | None = None,
    source_findings: list[str] | None = None,
) -> ScaleScoreReport:
    """Build a workflow-first report from direct workflow metadata without CSV datasets."""

    source_findings = list(source_findings or [])
    if document_operations_profile is not None:
        document_projection = derive_document_operations_readiness_inputs(
            document_operations_profile
        )
        if workflow_evidence is None:
            workflow_evidence = document_projection.workflow_evidence
        if operational_learning_inputs is None:
            operational_learning_inputs = document_projection.operational_learning_inputs
        source_findings.extend(document_projection.source_findings)

    operational_baseline = _workflow_operational_baseline_score(
        workflow_context=workflow_context,
        baseline_operational_score=baseline_operational_score,
    )

    report = ScaleScoreReport(
        report_id=str(uuid4()),
        org_id=org_id,
        org_name=org_name,
        assessment_mode=AssessmentMode.WORKFLOW,
        generated_at=datetime.now(UTC),
        overall_score=operational_baseline,
        overall_grade=_grade_for_score(operational_baseline),
        overall_trend="stable",
        area_scores=[],
        workflow_ref=workflow_ref,
        top_risks=[],
        constraints=[],
        recommendations=[],
        growth_signals=[],
        total_risks=0,
        critical_risks=0,
        high_risks=0,
        total_constraints=0,
        total_recommendations=0,
        executive_summary="",
        key_findings=_workflow_source_findings(workflow_context, source_findings),
        immediate_actions=[],
    )
    report = apply_workflow_readiness_context(report, workflow_context)
    report = apply_workflow_evidence_inputs(report, workflow_evidence)
    report = apply_operational_learning_inputs(report, operational_learning_inputs)

    workflow_score = report.workflow_readiness_score or operational_baseline
    workflow_grade = report.workflow_readiness_grade or _grade_for_score(workflow_score)
    key_findings = _workflow_key_findings(report, source_findings, workflow_evidence)
    immediate_actions = (
        report.prioritized_remediation_actions[:3]
        or report.immediate_actions
        or (
            report.operational_learning_suitability.recommended_next_actions[:3]
            if report.operational_learning_suitability is not None
            else []
        )
    )

    report = report.model_copy(
        update={
            "overall_score": workflow_score,
            "overall_grade": workflow_grade,
            "key_findings": key_findings,
            "immediate_actions": immediate_actions,
        }
    )
    report.executive_summary = generate_executive_summary(report)
    report = apply_assessment_ref(report, workflow_ref=workflow_ref)
    return report


def apply_assessment_ref(
    report: ScaleScoreReport,
    *,
    workflow_ref: WorkflowRefEnvelope | None = None,
) -> ScaleScoreReport:
    """Attach the compact Readiness-owned ref for workflow reports."""

    upstream_workflow_ref = workflow_ref or report.workflow_ref
    workflow_context = report.workflow_context
    if workflow_context is None and upstream_workflow_ref is None:
        return report

    score = (
        report.workflow_readiness_score
        if report.workflow_readiness_score is not None
        else report.overall_score
    )
    grade = report.workflow_readiness_grade or report.overall_grade
    workflow_id = (
        workflow_context.workflow_id
        if workflow_context is not None
        else upstream_workflow_ref.ref.workflow_id
        if upstream_workflow_ref is not None
        else None
    )
    workflow_name = (
        workflow_context.name
        if workflow_context is not None
        else upstream_workflow_ref.ref.title
        if upstream_workflow_ref is not None
        else "workflow"
    )
    report_uri = f"/api/v1/assessments/{report.report_id}"
    top_blockers = _assessment_ref_top_blockers(report)
    top_reasons = _assessment_ref_top_reasons(report)
    assessment_ref = AssessmentRefEnvelope(
        issued_at=report.generated_at,
        ref=AssessmentRef(
            ref_id=f"assessment:{report.org_id}:{report.report_id}",
            organization_id=report.org_id,
            external_uri=report_uri,
            version=report.report_version,
            created_at=report.generated_at,
            summary=(
                f"Workflow readiness assessment for {workflow_name}: "
                f"{score:.1f} ({grade or 'ungraded'})"
            ),
            assessment_id=report.report_id,
            workflow_id=workflow_id,
            workflow_ref=upstream_workflow_ref,
            score=score,
            grade=grade,
            status=_assessment_ref_status(score),
            top_blockers=top_blockers,
            top_reasons=top_reasons,
            report_uri=report_uri,
        ),
    )
    return report.model_copy(
        update={
            "workflow_ref": upstream_workflow_ref,
            "assessment_ref": assessment_ref,
        }
    )


def _assessment_ref_status(score: float) -> str:
    if score >= 80.0:
        return "ready"
    if score >= 65.0:
        return "watch"
    if score >= 50.0:
        return "at_risk"
    return "blocked"


def _assessment_ref_top_blockers(report: ScaleScoreReport) -> list[str]:
    blockers: list[str] = []
    if report.operational_learning_suitability is not None:
        blockers.extend(report.operational_learning_suitability.top_blockers)
    blockers.extend(report.top_trust_gaps)
    return list(dict.fromkeys(blocker for blocker in blockers if blocker))[:5]


def _assessment_ref_top_reasons(report: ScaleScoreReport) -> list[str]:
    reasons: list[str] = []
    if report.operational_learning_suitability is not None:
        reasons.extend(report.operational_learning_suitability.top_reasons)
    reasons.extend(report.key_findings)
    return list(dict.fromkeys(reason for reason in reasons if reason))[:5]


def _assessment_areas(
    constraint_by_area: dict[FunctionalArea, list[CapacityConstraint]],
    risk_by_area: dict[FunctionalArea, list[RiskIndicator]],
    growth_signals: list,
) -> list[FunctionalArea]:
    areas = {area for area, constraints in constraint_by_area.items() if constraints}
    areas.update(area for area, risks in risk_by_area.items() if risks)
    for signal in growth_signals:
        areas.update(signal.affected_areas)
    if not areas:
        return list(FunctionalArea)
    return [area for area in FunctionalArea if area in areas]


def _constraint_area(constraint: CapacityConstraint) -> FunctionalArea:
    if constraint.entity_type == "facility":
        return FunctionalArea.FACILITIES
    return FunctionalArea.OPERATIONS


def _overall_trend(area_scores: list) -> str:
    if not area_scores:
        return "stable"

    trends = [score.trend for score in area_scores]
    improving = trends.count("improving")
    declining = trends.count("declining")

    if declining > improving:
        return "declining"
    if improving > declining:
        return "improving"
    return "stable"


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


def _generate_key_findings(
    constraints: list[CapacityConstraint],
    risks: list[RiskIndicator],
) -> list[str]:
    findings: list[str] = []

    high_util_constraints = [c for c in constraints if c.current_utilization >= 0.9]
    if high_util_constraints:
        names = [c.entity_name for c in high_util_constraints[:3]]
        findings.append(
            f"{len(high_util_constraints)} system(s) at critical capacity: {', '.join(names)}"
        )

    critical_risks = [r for r in risks if r.risk_level == RiskLevel.CRITICAL]
    if critical_risks:
        findings.append(f"{len(critical_risks)} critical risk(s) require immediate attention")

    cascade_risks = [r for r in risks if r.category == "cascade_risk"]
    if cascade_risks:
        findings.append(f"{len(cascade_risks)} cascade risk(s) from dependency constraints")

    concentration_risks = [r for r in risks if r.category == "concentration_risk"]
    if concentration_risks:
        findings.append(f"{len(concentration_risks)} concentration risk(s) identified")

    return findings[:5]


def _generate_immediate_actions(recommendations: list) -> list[str]:
    high_priority = [r for r in recommendations if r.priority_score >= 1.5]
    return [r.title for r in high_priority[:3]]


def _workflow_operational_baseline_score(
    *,
    workflow_context: WorkflowAssessmentContext,
    baseline_operational_score: float | None,
) -> float:
    if baseline_operational_score is not None:
        return round(max(0.0, min(100.0, baseline_operational_score)), 1)

    documented_fields = [
        bool(workflow_context.owner),
        bool(workflow_context.ai_role),
        bool(workflow_context.systems_touched),
        bool(workflow_context.human_escalation_path),
        bool(workflow_context.control_requirements),
        bool(workflow_context.fallback_mode),
        bool(workflow_context.override_rights),
        bool(workflow_context.error_tolerance),
        bool(workflow_context.reversibility),
    ]
    coverage_ratio = sum(documented_fields) / len(documented_fields)
    blast_radius_adjustment = {
        WorkflowBlastRadius.LOW: 4.0,
        WorkflowBlastRadius.MEDIUM: 0.0,
        WorkflowBlastRadius.HIGH: -6.0,
        WorkflowBlastRadius.CRITICAL: -10.0,
    }[workflow_context.blast_radius]
    baseline = 45.0 + (coverage_ratio * 35.0) + blast_radius_adjustment
    return round(max(35.0, min(85.0, baseline)), 1)


def _workflow_source_findings(
    workflow_context: WorkflowAssessmentContext,
    source_findings: list[str],
) -> list[str]:
    findings = [
        f"Direct workflow assessment created for {workflow_context.name}.",
        *source_findings,
    ]
    return list(dict.fromkeys(finding for finding in findings if finding))[:5]


def _workflow_key_findings(
    report: ScaleScoreReport,
    source_findings: list[str],
    workflow_evidence: WorkflowEvidenceInput | None,
) -> list[str]:
    findings = [
        *source_findings,
        *_workflow_evidence_findings(workflow_evidence),
        f"Workflow readiness score: {(report.workflow_readiness_score or report.overall_score):.1f}.",
        *report.top_trust_gaps[:3],
    ]
    return list(dict.fromkeys(finding for finding in findings if finding))[:5]


def _workflow_evidence_findings(workflow_evidence: WorkflowEvidenceInput | None) -> list[str]:
    if workflow_evidence is None:
        return []

    findings: list[str] = []
    if workflow_evidence.control_coverage is not None:
        covered_controls = _workflow_control_coverage_count(workflow_evidence.control_coverage)
        findings.append(
            f"Explicit workflow control coverage was provided for {covered_controls} control area(s)."
        )
    if workflow_evidence.evidence_posture is not None:
        findings.extend(_workflow_evidence_posture_findings(workflow_evidence.evidence_posture))
    if workflow_evidence.approval_evidence_count is not None:
        findings.append(
            f"Workflow evidence includes {workflow_evidence.approval_evidence_count} approval artifact(s)."
        )
    if workflow_evidence.decision_log_count is not None:
        findings.append(
            f"Workflow evidence includes {workflow_evidence.decision_log_count} decision log sample(s)."
        )
    if workflow_evidence.escalation_tested is False:
        findings.append("Human escalation path has not been tested.")
    elif workflow_evidence.escalation_tested is True:
        findings.append("Human escalation path has been tested.")
    if workflow_evidence.rollback_tested is False:
        findings.append("Rollback path has not been tested.")
    elif workflow_evidence.rollback_tested is True:
        findings.append("Rollback path has been tested.")
    return list(dict.fromkeys(findings))[:5]


def _workflow_control_coverage_count(control_coverage: WorkflowControlCoverageInput) -> int:
    return sum(
        1
        for value in (
            control_coverage.approval_gate,
            control_coverage.decision_logging,
            control_coverage.evidence_retention,
            control_coverage.exception_handling,
            control_coverage.periodic_review,
        )
        if value is not None
    )


def _workflow_evidence_posture_findings(
    evidence_posture: WorkflowEvidencePostureInput,
) -> list[str]:
    findings: list[str] = []
    if evidence_posture.control_evidence_coverage_percent is not None:
        findings.append(
            "Control evidence coverage is "
            f"{evidence_posture.control_evidence_coverage_percent:.1f}%."
        )
    if evidence_posture.freshest_evidence_age_days is not None:
        findings.append(
            f"Freshest control evidence is {evidence_posture.freshest_evidence_age_days} day(s) old."
        )
    if evidence_posture.audit_trail_complete is True:
        findings.append("Audit trail completeness is confirmed.")
    elif evidence_posture.audit_trail_complete is False:
        findings.append("Audit trail completeness is not confirmed.")
    return findings
