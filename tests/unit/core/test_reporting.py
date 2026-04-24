from datetime import UTC, datetime

from scalescore.core.operational_learning import score_operational_learning_suitability
from scalescore.core.reporting import generate_executive_summary, render_report_pdf
from scalescore.models.scaling import (
    OperationalLearningCompletenessState,
    OperationalLearningGovernanceDependencyInput,
    OperationalLearningInputs,
    RiskLevel,
    ScaleScoreReport,
    WorkflowAssessmentContext,
    WorkflowBlastRadius,
)


def _sample_report() -> ScaleScoreReport:
    return ScaleScoreReport(
        report_id="report_1",
        org_id="org_1",
        org_name="Acme",
        generated_at=datetime.now(UTC),
        overall_score=78.4,
        overall_grade="C",
        overall_trend="stable",
        total_risks=6,
        critical_risks=1,
        high_risks=2,
        total_constraints=4,
        key_findings=["2 system(s) at critical capacity"],
        immediate_actions=["Expand capacity for Billing"],
        executive_summary="",
    )


def test_generate_executive_summary_includes_core_metrics() -> None:
    report = _sample_report()

    summary = generate_executive_summary(report)

    assert "Acme" in summary
    assert "78.4" in summary
    assert "critical" in summary.lower()


def test_render_report_pdf_returns_pdf_bytes() -> None:
    report = _sample_report()
    report.executive_summary = generate_executive_summary(report)

    pdf_bytes = render_report_pdf(report)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_generate_executive_summary_uses_workflow_context_when_present() -> None:
    report = _sample_report()
    report.workflow_context = WorkflowAssessmentContext(
        workflow_id="wf_support",
        name="Support Triage",
        business_function="operations",
        owner="COO",
        ai_role="Classify and route inbound tickets",
        systems_touched=["sys_support"],
        human_escalation_path=["Support Manager", "COO"],
        control_requirements=["decision logging"],
        blast_radius=WorkflowBlastRadius.MEDIUM,
    )
    report.workflow_readiness_score = 81.0
    report.workflow_readiness_grade = "B"
    report.top_trust_gaps = ["Fallback mode is not documented."]
    report.prioritized_remediation_actions = ["Document fallback mode before wider rollout."]

    summary = generate_executive_summary(report)

    assert "Support Triage" in summary
    assert "AI operational readiness" in summary
    assert "Fallback mode is not documented." in summary


def test_generate_executive_summary_mentions_operational_learning_when_present() -> None:
    report = _sample_report()
    report.workflow_context = WorkflowAssessmentContext(
        workflow_id="wf_support",
        name="Support Triage",
        business_function="operations",
        owner="COO",
        ai_role="Classify and route inbound tickets",
        systems_touched=["sys_support"],
        human_escalation_path=["Support Manager", "COO"],
        control_requirements=["decision logging"],
        blast_radius=WorkflowBlastRadius.MEDIUM,
    )
    report.workflow_readiness_score = 81.0
    report.workflow_readiness_grade = "B"
    report.top_trust_gaps = ["Fallback mode is not documented."]
    report.prioritized_remediation_actions = ["Document fallback mode before wider rollout."]
    report.operational_learning_suitability = score_operational_learning_suitability(
        OperationalLearningInputs(
            sop_reference_present=True,
            sop_clarity_signal=84.0,
            outcome_spec_present=True,
            outcome_observability_signal=86.0,
            repeatability_signal=88.0,
            review_path_present=True,
            review_density_signal=78.0,
            redaction_manageability_signal=82.0,
            governance_dependency_state=OperationalLearningGovernanceDependencyInput(
                rights_completeness=OperationalLearningCompletenessState.COMPLETE,
                provenance_completeness=OperationalLearningCompletenessState.COMPLETE,
                redaction_readiness=OperationalLearningCompletenessState.COMPLETE,
                residual_risk_band=RiskLevel.LOW,
            ),
        )
    )

    summary = generate_executive_summary(report)

    assert "Operational Learning suitability" in summary
    assert "training candidate" in summary
