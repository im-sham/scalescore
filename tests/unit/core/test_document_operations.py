from scalescore.core.document_operations import derive_document_operations_readiness_inputs
from scalescore.core.operational_learning import score_operational_learning_suitability
from scalescore.models.scaling import (
    DocumentOperationsReadinessProfile,
    OperationalLearningCompletenessState,
    OperationalLearningGovernanceDependencyInput,
    OperationalLearningGovernanceStateStatus,
    OperationalLearningSuitabilityStatus,
    RiskLevel,
    WorkflowControlStatus,
)


def _governance_state(
    *,
    rights: OperationalLearningCompletenessState,
    provenance: OperationalLearningCompletenessState,
    redaction: OperationalLearningCompletenessState,
    risk: RiskLevel,
) -> OperationalLearningGovernanceDependencyInput:
    return OperationalLearningGovernanceDependencyInput(
        rights_completeness=rights,
        provenance_completeness=provenance,
        redaction_readiness=redaction,
        residual_risk_band=risk,
    )


def test_document_operations_profile_derives_training_candidate_inputs() -> None:
    projection = derive_document_operations_readiness_inputs(
        DocumentOperationsReadinessProfile(
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
            governance_dependency_state=_governance_state(
                rights=OperationalLearningCompletenessState.COMPLETE,
                provenance=OperationalLearningCompletenessState.COMPLETE,
                redaction=OperationalLearningCompletenessState.COMPLETE,
                risk=RiskLevel.LOW,
            ),
        )
    )

    assert projection.workflow_evidence.control_coverage is not None
    assert projection.workflow_evidence.control_coverage.approval_gate == WorkflowControlStatus.VERIFIED
    assert projection.workflow_evidence.evidence_posture is not None
    assert projection.workflow_evidence.evidence_posture.audit_trail_complete is True
    assert any("document_ops_regulated_review_v0" in finding for finding in projection.source_findings)

    suitability = score_operational_learning_suitability(
        projection.operational_learning_inputs
    )

    assert suitability.status == OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE
    assert suitability.top_blockers == []
    assert suitability.governance_dependency_state.status == OperationalLearningGovernanceStateStatus.READY


def test_document_operations_profile_blocks_when_redaction_dependency_is_missing() -> None:
    projection = derive_document_operations_readiness_inputs(
        DocumentOperationsReadinessProfile(
            fixture_id="document_ops_regulated_review_v0",
            subject_type="document_packet",
            subject_key="claims-benefits-sample",
            normal_case_closed_with_evidence=True,
            exception_case_escalated=True,
            exception_requires_compliance_signoff=True,
            redaction_review_required_before_internal_eval=True,
            sop_refs_present=True,
            outcome_refs_present=True,
            required_document_rules_present=True,
            evidence_refs_present=True,
            weekly_packet_volume=40.0,
            reviewed_case_count=20,
            source_evidence_ref_count=8,
            governance_dependency_state=_governance_state(
                rights=OperationalLearningCompletenessState.COMPLETE,
                provenance=OperationalLearningCompletenessState.COMPLETE,
                redaction=OperationalLearningCompletenessState.MISSING,
                risk=RiskLevel.LOW,
            ),
        )
    )

    suitability = score_operational_learning_suitability(
        projection.operational_learning_inputs
    )

    assert suitability.status == OperationalLearningSuitabilityStatus.BLOCKED
    assert any("redaction readiness" in blocker for blocker in suitability.top_blockers)


def test_document_operations_profile_marks_weak_candidate_without_hard_blockers() -> None:
    projection = derive_document_operations_readiness_inputs(
        DocumentOperationsReadinessProfile(
            fixture_id="document_ops_regulated_review_v0",
            subject_type="document_packet",
            subject_key="claims-benefits-sample",
            normal_case_closed_with_evidence=True,
            exception_case_escalated=True,
            exception_requires_compliance_signoff=True,
            redaction_review_required_before_internal_eval=True,
            sop_refs_present=True,
            outcome_refs_present=True,
            required_document_rules_present=True,
            evidence_refs_present=True,
            weekly_packet_volume=4.0,
            reviewed_case_count=3,
            source_evidence_ref_count=2,
            control_evidence_coverage_percent=58.0,
            freshest_evidence_age_days=61,
            governance_dependency_state=_governance_state(
                rights=OperationalLearningCompletenessState.PARTIAL,
                provenance=OperationalLearningCompletenessState.PARTIAL,
                redaction=OperationalLearningCompletenessState.PARTIAL,
                risk=RiskLevel.MEDIUM,
            ),
        )
    )

    suitability = score_operational_learning_suitability(
        projection.operational_learning_inputs
    )

    assert suitability.status == OperationalLearningSuitabilityStatus.WEAK_CANDIDATE
    assert suitability.top_blockers == []
    assert suitability.eval_suitability.threshold_met is False
    assert suitability.governance_dependency_state.status == OperationalLearningGovernanceStateStatus.PARTIAL
