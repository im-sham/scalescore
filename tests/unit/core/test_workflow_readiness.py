from datetime import UTC, datetime

from scalescore.core.workflow_readiness import (
    apply_workflow_evidence_inputs,
    apply_workflow_readiness_context,
    derive_org_workflow_rollup,
)
from scalescore.models.scaling import (
    Recommendation,
    ScaleScoreReport,
    WorkflowAssessmentContext,
    WorkflowBlastRadius,
    WorkflowControlCoverageInput,
    WorkflowControlStatus,
    WorkflowEvidenceInput,
    WorkflowEvidencePostureInput,
    WorkflowReadinessPillar,
)


def _workflow_context(workflow_id: str, name: str) -> WorkflowAssessmentContext:
    return WorkflowAssessmentContext(
        workflow_id=workflow_id,
        name=name,
        business_function="operations",
        owner="COO",
        ai_role="Triage and route inbound work",
        systems_touched=["sys_ops"],
        human_escalation_path=["Ops Manager", "COO"],
        control_requirements=["approval logging", "decision traceability"],
        blast_radius=WorkflowBlastRadius.MEDIUM,
        fallback_mode="Manual queue review",
        override_rights=["Ops Manager", "COO"],
        error_tolerance="Low",
        reversibility="Routing changes can be reverted within the same shift",
    )


def _base_report(report_id: str, score: float) -> ScaleScoreReport:
    return ScaleScoreReport(
        report_id=report_id,
        org_id="org_1",
        org_name="Acme",
        generated_at=datetime.now(UTC),
        overall_score=score,
        overall_grade="B",
        overall_trend="stable",
        total_risks=2,
        critical_risks=0,
        high_risks=1,
        total_constraints=1,
        total_recommendations=1,
        recommendations=[
            Recommendation(
                id=f"rec_{report_id}",
                org_id="org_1",
                title="Document fallback and escalation playbook",
                description="Capture the human fallback procedure before expanding automation.",
                recommendation_type="governance",
                target_entity_id="sys_ops",
                target_entity_type="system",
                effort="medium",
                impact="high",
            )
        ],
    )


def test_apply_workflow_readiness_context_enriches_report() -> None:
    report = apply_workflow_readiness_context(
        _base_report("report_1", 82.0),
        _workflow_context("wf_support", "Support Triage"),
    )

    assert report.workflow_readiness_score is not None
    assert report.workflow_readiness_grade
    assert len(report.workflow_pillar_scores) == 5
    assert report.top_trust_gaps == [] or isinstance(report.top_trust_gaps[0], str)
    assert report.prioritized_remediation_actions[0] == "Document fallback and escalation playbook"
    assert report.org_rollup is not None
    assert report.org_rollup.average_workflow_score == report.workflow_readiness_score


def test_derive_org_workflow_rollup_averages_multiple_reports() -> None:
    report_a = apply_workflow_readiness_context(
        _base_report("report_a", 82.0),
        _workflow_context("wf_support", "Support Triage"),
    )
    report_b = apply_workflow_readiness_context(
        _base_report("report_b", 68.0),
        _workflow_context("wf_finance", "Finance Close"),
    )

    rollup = derive_org_workflow_rollup([report_a, report_b])

    assert rollup.org_id == "org_1"
    assert rollup.workflow_count == 2
    assert set(rollup.workflow_ids) == {"wf_support", "wf_finance"}
    assert rollup.average_workflow_score == round(
        ((report_a.workflow_readiness_score or 0.0) + (report_b.workflow_readiness_score or 0.0))
        / 2,
        1,
    )


def test_apply_workflow_evidence_inputs_scores_explicit_control_coverage() -> None:
    base_report = apply_workflow_readiness_context(
        _base_report("report_control", 78.0),
        _workflow_context("wf_support", "Support Triage"),
    )

    weak_report = apply_workflow_evidence_inputs(
        base_report,
        WorkflowEvidenceInput(
            control_coverage=WorkflowControlCoverageInput(
                approval_gate=WorkflowControlStatus.DOCUMENTED,
                decision_logging=WorkflowControlStatus.MISSING,
                evidence_retention=WorkflowControlStatus.DOCUMENTED,
                exception_handling=WorkflowControlStatus.MISSING,
                periodic_review=WorkflowControlStatus.MISSING,
            ),
            evidence_posture=WorkflowEvidencePostureInput(
                control_evidence_coverage_percent=42.0,
                freshest_evidence_age_days=240,
                audit_trail_complete=False,
                linked_artifacts=False,
            ),
        ),
    )
    strong_report = apply_workflow_evidence_inputs(
        base_report,
        WorkflowEvidenceInput(
            control_coverage=WorkflowControlCoverageInput(
                approval_gate=WorkflowControlStatus.VERIFIED,
                decision_logging=WorkflowControlStatus.VERIFIED,
                evidence_retention=WorkflowControlStatus.OPERATING,
                exception_handling=WorkflowControlStatus.OPERATING,
                periodic_review=WorkflowControlStatus.VERIFIED,
            ),
            evidence_posture=WorkflowEvidencePostureInput(
                control_evidence_coverage_percent=96.0,
                freshest_evidence_age_days=14,
                audit_trail_complete=True,
                linked_artifacts=True,
            ),
        ),
    )

    weak_control = next(
        pillar
        for pillar in weak_report.workflow_pillar_scores
        if pillar.pillar == WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS
    )
    strong_control = next(
        pillar
        for pillar in strong_report.workflow_pillar_scores
        if pillar.pillar == WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS
    )

    assert strong_control.score > weak_control.score
    assert any("verified by source evidence" in strength for strength in strong_control.strengths)
    assert any("missing from the workflow control coverage" in gap for gap in weak_control.gaps)
