from pathlib import Path

import pytest

from scalescore.config import settings
from scalescore.core.assessment import (
    run_assessment,
    run_assessment_from_csv,
    run_workflow_assessment,
)
from scalescore.models.core import Facility, Organization, System
from scalescore.models.scaling import (
    DocumentOperationsReadinessProfile,
    FunctionalArea,
    OperationalLearningCompletenessState,
    OperationalLearningGovernanceDependencyInput,
    OperationalLearningInputs,
    OperationalLearningSuitabilityStatus,
    RiskLevel,
    WorkflowAssessmentContext,
    WorkflowBlastRadius,
    WorkflowControlCoverageInput,
    WorkflowControlStatus,
    WorkflowEvidenceInput,
    WorkflowEvidencePostureInput,
    WorkflowReadinessPillar,
)


def test_run_assessment_builds_constraints_and_scores() -> None:
    organization = Organization(id="org_1", name="Acme")
    system = System(
        id="sys_1",
        org_id="org_1",
        name="Billing",
        system_type="erp",
        capacity_current=90,
        capacity_max=100,
        capacity_unit="users",
    )
    facility = Facility(
        id="fac_1",
        org_id="org_1",
        name="HQ",
        facility_type="office",
        location="SF",
        capacity_seats=100,
        capacity_used=90,
    )

    report = run_assessment(
        organizations=[organization],
        systems=[system],
        facilities=[facility],
        growth_signals=[],
    )

    assert report.total_constraints == 2
    assert report.area_scores
    assert report.overall_score < 100


def test_run_assessment_rejects_multiple_orgs() -> None:
    from scalescore.core.exceptions import MultipleOrganizationsError

    org_a = Organization(id="org_a", name="Acme")
    org_b = Organization(id="org_b", name="Beta")

    with pytest.raises(MultipleOrganizationsError, match="single organization"):
        run_assessment(
            organizations=[org_a, org_b],
            systems=[],
            facilities=[],
            growth_signals=[],
        )


def test_run_assessment_uses_settings_based_scoring(monkeypatch) -> None:
    monkeypatch.setattr(settings.scoring, "base_score", 82.0)

    report = run_assessment(
        organizations=[Organization(id="org_1", name="Acme")],
        systems=[],
        facilities=[],
        growth_signals=[],
    )

    assert report.overall_score == 82.0
    assert report.area_scores
    assert all(score.score == 82.0 for score in report.area_scores)


def test_run_assessment_from_csv(tmp_path: Path) -> None:
    (tmp_path / "organizations.csv").write_text(
        "id,name,headcount_current,revenue_current,burn_rate_monthly,runway_months\n"
        "org_1,Acme,100,1000000,50000,18\n",
        encoding="utf-8",
    )
    (tmp_path / "teams.csv").write_text(
        "id,org_id,name,function,headcount_current,parent_team_id,manager_id\n"
        "team_1,org_1,Engineering,engineering,50,,mgr_1\n",
        encoding="utf-8",
    )
    (tmp_path / "systems.csv").write_text(
        "id,org_id,name,system_type,capacity_current,capacity_max,capacity_unit,is_critical,dependencies\n"
        "sys_1,org_1,CRM,crm,90,100,users,true,\n",
        encoding="utf-8",
    )
    (tmp_path / "vendors.csv").write_text(
        "id,org_id,name,vendor_type,annual_cost,is_critical,alternatives\n"
        "ven_1,org_1,AWS,saas,100000,true,Azure|GCP\n",
        encoding="utf-8",
    )
    (tmp_path / "facilities.csv").write_text(
        "id,org_id,name,facility_type,location,capacity_seats,capacity_used,lease_end_date\n"
        "fac_1,org_1,HQ,office,SF,100,90,2027-06-30\n",
        encoding="utf-8",
    )
    (tmp_path / "growth_signals.csv").write_text(
        "id,org_id,signal_type,title,target_date,magnitude,magnitude_type,confidence,affected_areas\n"
        "sig_1,org_1,headcount_plan,Scale,2026-12-31,100,percentage,0.8,engineering|operations\n",
        encoding="utf-8",
    )

    report = run_assessment_from_csv(tmp_path)

    assert report.org_id == "org_1"
    assert report.area_scores
    assert report.area_scores[0].functional_area in {
        FunctionalArea.ENGINEERING,
        FunctionalArea.OPERATIONS,
        FunctionalArea.FACILITIES,
    }


def test_run_assessment_can_enrich_with_workflow_readiness_context() -> None:
    organization = Organization(id="org_1", name="Acme")
    system = System(
        id="sys_billing",
        org_id="org_1",
        name="Billing",
        system_type="erp",
        capacity_current=90,
        capacity_max=100,
        capacity_unit="users",
        dependencies=["sys_crm"],
    )
    workflow_context = WorkflowAssessmentContext(
        workflow_id="wf_finance_close",
        name="Finance Close Automation",
        business_function="finance",
        owner="Controller",
        ai_role="Draft close-pack anomalies and reconciliation recommendations",
        systems_touched=["sys_billing", "Billing"],
        human_escalation_path=["Controller", "CFO"],
        control_requirements=["approval traceability", "decision logging"],
        blast_radius=WorkflowBlastRadius.HIGH,
        fallback_mode="Manual finance close process",
        override_rights=["Controller", "CFO"],
        error_tolerance="Low tolerance for misclassification in month-end close",
        reversibility="All AI-produced adjustments require human approval before posting",
    )

    report = run_assessment(
        organizations=[organization],
        systems=[system],
        facilities=[],
        growth_signals=[],
        workflow_context=workflow_context,
    )

    assert report.assessment_mode == "workflow"
    assert report.workflow_context is not None
    assert report.workflow_context.workflow_id == "wf_finance_close"
    assert report.workflow_readiness_score is not None
    assert report.workflow_readiness_grade is not None
    assert len(report.workflow_pillar_scores) == 5
    assert report.top_trust_gaps
    assert report.prioritized_remediation_actions
    assert report.org_rollup is not None
    assert report.org_rollup.workflow_count == 1
    assert report.assessment_ref is not None
    assert report.assessment_ref.contract_name == "AssessmentRef"
    assert report.assessment_ref.ref.assessment_id == report.report_id
    assert report.assessment_ref.ref.workflow_id == "wf_finance_close"


def test_run_workflow_assessment_uses_structured_workflow_evidence() -> None:
    workflow_context = WorkflowAssessmentContext(
        workflow_id="wf_finance_close",
        name="Finance Close Automation",
        business_function="finance",
        owner="Controller",
        ai_role="Draft close-pack anomalies and reconciliation recommendations",
        systems_touched=["sys_billing", "Billing"],
        human_escalation_path=["Controller", "CFO"],
        control_requirements=["approval traceability", "decision logging"],
        blast_radius=WorkflowBlastRadius.HIGH,
        fallback_mode="Manual finance close process",
        override_rights=["Controller", "CFO"],
        error_tolerance="Low tolerance for misclassification in month-end close",
        reversibility="All AI-produced adjustments require human approval before posting",
    )

    weak_report = run_workflow_assessment(
        org_id="org_1",
        org_name="Acme",
        workflow_context=workflow_context,
        baseline_operational_score=78.0,
        workflow_evidence=WorkflowEvidenceInput(
            control_coverage=WorkflowControlCoverageInput(
                approval_gate=WorkflowControlStatus.DOCUMENTED,
                decision_logging=WorkflowControlStatus.MISSING,
                evidence_retention=WorkflowControlStatus.DOCUMENTED,
                exception_handling=WorkflowControlStatus.MISSING,
                periodic_review=WorkflowControlStatus.MISSING,
            ),
            evidence_posture=WorkflowEvidencePostureInput(
                control_evidence_coverage_percent=45.0,
                freshest_evidence_age_days=210,
                audit_trail_complete=False,
                linked_artifacts=False,
            ),
            owner_confirmed=False,
            systems_verified=False,
            escalation_tested=False,
            fallback_tested=False,
            override_reviewed=False,
            approval_evidence_count=0,
            decision_log_count=0,
            rollback_tested=False,
        ),
    )
    strong_report = run_workflow_assessment(
        org_id="org_1",
        org_name="Acme",
        workflow_context=workflow_context,
        baseline_operational_score=78.0,
        workflow_evidence=WorkflowEvidenceInput(
            control_coverage=WorkflowControlCoverageInput(
                approval_gate=WorkflowControlStatus.VERIFIED,
                decision_logging=WorkflowControlStatus.VERIFIED,
                evidence_retention=WorkflowControlStatus.OPERATING,
                exception_handling=WorkflowControlStatus.OPERATING,
                periodic_review=WorkflowControlStatus.VERIFIED,
            ),
            evidence_posture=WorkflowEvidencePostureInput(
                control_evidence_coverage_percent=94.0,
                freshest_evidence_age_days=18,
                audit_trail_complete=True,
                linked_artifacts=True,
            ),
            owner_confirmed=True,
            systems_verified=True,
            escalation_tested=True,
            fallback_tested=True,
            override_reviewed=True,
            approval_evidence_count=4,
            decision_log_count=18,
            rollback_tested=True,
        ),
    )

    assert strong_report.workflow_readiness_score is not None
    assert weak_report.workflow_readiness_score is not None
    assert strong_report.workflow_readiness_score > weak_report.workflow_readiness_score

    strong_control = next(
        pillar
        for pillar in strong_report.workflow_pillar_scores
        if pillar.pillar == WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS
    )
    weak_control = next(
        pillar
        for pillar in weak_report.workflow_pillar_scores
        if pillar.pillar == WorkflowReadinessPillar.CONTROL_AND_EVIDENCE_READINESS
    )
    weak_automation = next(
        pillar
        for pillar in weak_report.workflow_pillar_scores
        if pillar.pillar == WorkflowReadinessPillar.AUTOMATION_FIT_AND_BLAST_RADIUS
    )

    assert strong_control.score > weak_control.score
    assert any("verified by source evidence" in strength for strength in strong_control.strengths)
    assert "Workflow evidence includes 4 approval artifact(s)." in strong_report.key_findings
    assert "Explicit workflow control coverage was provided for 5 control area(s)." in strong_report.key_findings
    assert any("Rollback path has not been tested" in gap for gap in weak_automation.gaps)


def test_run_workflow_assessment_adds_operational_learning_suitability() -> None:
    workflow_context = WorkflowAssessmentContext(
        workflow_id="wf_finance_close",
        name="Finance Close Automation",
        business_function="finance",
        owner="Controller",
        ai_role="Draft close-pack anomalies and reconciliation recommendations",
        systems_touched=["sys_billing", "Billing"],
        human_escalation_path=["Controller", "CFO"],
        control_requirements=["approval traceability", "decision logging"],
        blast_radius=WorkflowBlastRadius.HIGH,
        fallback_mode="Manual finance close process",
        override_rights=["Controller", "CFO"],
        error_tolerance="Low tolerance for misclassification in month-end close",
        reversibility="All AI-produced adjustments require human approval before posting",
    )

    report = run_workflow_assessment(
        org_id="org_1",
        org_name="Acme",
        workflow_context=workflow_context,
        baseline_operational_score=78.0,
        operational_learning_inputs=OperationalLearningInputs(
            sop_reference_present=True,
            sop_clarity_signal=82.0,
            outcome_spec_present=True,
            outcome_observability_signal=85.0,
            repeatability_signal=86.0,
            review_path_present=True,
            review_density_signal=74.0,
            redaction_manageability_signal=80.0,
            governance_dependency_state=OperationalLearningGovernanceDependencyInput(
                rights_completeness=OperationalLearningCompletenessState.COMPLETE,
                provenance_completeness=OperationalLearningCompletenessState.COMPLETE,
                redaction_readiness=OperationalLearningCompletenessState.COMPLETE,
                residual_risk_band=RiskLevel.LOW,
            ),
        ),
    )

    assert report.workflow_readiness_score is not None
    assert report.overall_score == report.workflow_readiness_score
    assert report.operational_learning_suitability is not None
    assert (
        report.operational_learning_suitability.status
        == OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE
    )
    assert report.operational_learning_suitability.top_blockers == []


def test_run_workflow_assessment_marks_operational_learning_blocked_when_governance_inputs_missing() -> None:
    workflow_context = WorkflowAssessmentContext(
        workflow_id="wf_finance_close",
        name="Finance Close Automation",
        business_function="finance",
        owner="Controller",
        ai_role="Draft close-pack anomalies and reconciliation recommendations",
        systems_touched=["sys_billing", "Billing"],
        human_escalation_path=["Controller", "CFO"],
        control_requirements=["approval traceability", "decision logging"],
        blast_radius=WorkflowBlastRadius.HIGH,
        fallback_mode="Manual finance close process",
        override_rights=["Controller", "CFO"],
        error_tolerance="Low tolerance for misclassification in month-end close",
        reversibility="All AI-produced adjustments require human approval before posting",
    )

    report = run_workflow_assessment(
        org_id="org_1",
        org_name="Acme",
        workflow_context=workflow_context,
        baseline_operational_score=78.0,
        operational_learning_inputs=OperationalLearningInputs(
            sop_reference_present=True,
            sop_clarity_signal=72.0,
            outcome_spec_present=True,
            outcome_observability_signal=74.0,
            repeatability_signal=79.0,
            review_path_present=True,
            review_density_signal=67.0,
            redaction_manageability_signal=75.0,
        ),
    )

    assert report.operational_learning_suitability is not None
    assert report.workflow_readiness_score is not None
    assert (
        report.operational_learning_suitability.status
        == OperationalLearningSuitabilityStatus.BLOCKED
    )
    assert any(
        "Governance dependency state is missing" in blocker
        for blocker in report.operational_learning_suitability.top_blockers
    )


def test_run_workflow_assessment_scores_document_operations_profile() -> None:
    workflow_context = WorkflowAssessmentContext(
        workflow_id="document_ops_regulated_review_v0",
        name="Claims and Benefits Packet Review",
        business_function="document_operations",
        owner="Document Operations Lead",
        ai_role="Classify packets, extract fields, and route exception cases for human review",
        systems_touched=["intake_queue", "document_store", "review_console"],
        human_escalation_path=["Document Operations Lead", "Compliance Reviewer"],
        control_requirements=[
            "required document checks",
            "review-required decision logging",
            "evidence retention",
        ],
        blast_radius=WorkflowBlastRadius.HIGH,
        fallback_mode="Manual packet review with compliance escalation",
        override_rights=["Document Operations Lead", "Compliance Reviewer"],
        error_tolerance="Low tolerance for unsupported eligibility or benefit determinations",
        reversibility="Reviewer decisions can be corrected before downstream packaging.",
    )

    report = run_workflow_assessment(
        org_id="tenant_default",
        org_name="Default Tenant",
        workflow_context=workflow_context,
        baseline_operational_score=84.0,
        document_operations_profile=DocumentOperationsReadinessProfile(
            fixture_id="document_ops_regulated_review_v0",
            subject_type="document_packet",
            subject_key="claims-benefits-sample",
            normal_case_id="normal-packet",
            normal_case_state="closed_with_evidence",
            normal_case_closed_with_evidence=True,
            exception_case_id="exception-packet",
            exception_case_state="requires_compliance_signoff",
            exception_case_escalated=True,
            exception_requires_compliance_signoff=True,
            redaction_review_required_before_internal_eval=True,
            sop_refs_present=True,
            outcome_refs_present=True,
            required_document_rules_present=True,
            evidence_refs_present=True,
            owner_confirmed=True,
            systems_verified=True,
            review_sla_defined=True,
            weekly_packet_volume=55.0,
            reviewed_case_count=42,
            source_evidence_ref_count=12,
            control_evidence_coverage_percent=96.0,
            freshest_evidence_age_days=6,
            governance_dependency_state=OperationalLearningGovernanceDependencyInput(
                rights_completeness=OperationalLearningCompletenessState.COMPLETE,
                provenance_completeness=OperationalLearningCompletenessState.COMPLETE,
                redaction_readiness=OperationalLearningCompletenessState.COMPLETE,
                residual_risk_band=RiskLevel.LOW,
            ),
        ),
    )

    assert report.workflow_readiness_score is not None
    assert len(report.workflow_pillar_scores) == 5
    assert report.overall_score == report.workflow_readiness_score
    assert report.assessment_ref is not None
    assert report.assessment_ref.contract_version == "proofhouse-shared-contracts/v0.1"
    assert report.assessment_ref.ref.assessment_type == "workflow_readiness"
    assert report.assessment_ref.ref.workflow_id == "document_ops_regulated_review_v0"
    assert report.operational_learning_suitability is not None
    assert (
        report.operational_learning_suitability.status
        == OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE
    )
    assert any("document_ops_regulated_review_v0" in finding for finding in report.key_findings)
