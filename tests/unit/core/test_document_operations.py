from scalescore.core.document_operations import derive_document_operations_readiness_inputs
from scalescore.core.operational_learning import score_operational_learning_suitability
from scalescore.models.scaling import (
    ClaimsReadinessState,
    ClaimsSuitabilityStatus,
    ClaimsWorkflowReadinessProfile,
    DocumentOperationsReadinessProfile,
    OperationalLearningCompletenessState,
    OperationalLearningGovernanceDependencyInput,
    OperationalLearningGovernanceStateStatus,
    OperationalLearningSuitabilityStatus,
    RiskLevel,
    WorkflowControlStatus,
)

CLAIMS_EVIDENCE_CLASSES = [
    "claim_packet",
    "claim_line",
    "invoice_provider_bill",
    "eob_remittance_evidence",
    "policy_plan_document",
    "contract_rate_source",
    "specialist_review_note",
    "downstream_export_record",
    "savings_recognition_record",
    "audit_packet",
]


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


def _claims_profile(**overrides: object) -> ClaimsWorkflowReadinessProfile:
    values = {
        "profile_id": "claims-hybrid-high-dollar-review-v0",
        "evidence_class_ids_present": CLAIMS_EVIDENCE_CLASSES,
        "phi_boundary_review_state": ClaimsReadinessState.REVIEWED,
        "redaction_review_state": ClaimsReadinessState.REVIEWED,
        "rate_source_review_state": ClaimsReadinessState.REVIEWED,
        "downstream_consistency_state": ClaimsReadinessState.READY,
        "downstream_action_approval_state": ClaimsReadinessState.APPROVED,
        "savings_recognition_state": ClaimsReadinessState.APPROVED,
        "governance_claims_control_state": ClaimsReadinessState.READY,
        "source_readiness_state": ClaimsReadinessState.READY,
    }
    values.update(overrides)
    return ClaimsWorkflowReadinessProfile(**values)


def _document_operations_profile(
    *,
    claims_profile: ClaimsWorkflowReadinessProfile | None = None,
) -> DocumentOperationsReadinessProfile:
    return DocumentOperationsReadinessProfile(
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
        claims_profile=claims_profile,
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
    assert projection.claims_suitability is None


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


def test_document_operations_claims_profile_can_be_eval_suitable() -> None:
    projection = derive_document_operations_readiness_inputs(
        _document_operations_profile(claims_profile=_claims_profile())
    )

    assert projection.claims_suitability is not None
    assert projection.claims_suitability.profile_id == "claims-hybrid-high-dollar-review-v0"
    assert projection.claims_suitability.status == ClaimsSuitabilityStatus.EVAL_SUITABLE
    assert projection.claims_suitability.score >= 80.0
    assert projection.claims_suitability.top_blockers == []
    assert projection.claims_suitability.evidence_gap_state == "ready"
    assert projection.claims_suitability.phi_redaction_state == "ready"
    assert projection.claims_suitability.rate_source_traceability_state == "ready"
    assert projection.claims_suitability.downstream_consistency_state == "ready"
    assert projection.claims_suitability.savings_lifecycle_state == "ready"


def test_document_operations_claims_profile_blocks_missing_phi_redaction_or_governance() -> None:
    projection = derive_document_operations_readiness_inputs(
        _document_operations_profile(
            claims_profile=_claims_profile(
                phi_boundary_review_state=ClaimsReadinessState.REVIEW_REQUIRED,
                redaction_review_state=ClaimsReadinessState.MISSING,
                governance_claims_control_state=ClaimsReadinessState.BLOCKED,
            )
        )
    )

    assert projection.claims_suitability is not None
    assert projection.claims_suitability.status == ClaimsSuitabilityStatus.BLOCKED
    assert any("PHI boundary" in blocker for blocker in projection.claims_suitability.top_blockers)
    assert any("redaction" in blocker for blocker in projection.claims_suitability.top_blockers)
    assert any("Governance claims controls" in blocker for blocker in projection.claims_suitability.top_blockers)
    assert projection.operational_learning_inputs.redaction_manageability_signal == 30.0


def test_document_operations_claims_profile_marks_rate_source_gap_as_weak_candidate() -> None:
    projection = derive_document_operations_readiness_inputs(
        _document_operations_profile(
            claims_profile=_claims_profile(
                rate_source_review_state=ClaimsReadinessState.UNVERIFIED,
            )
        )
    )

    assert projection.claims_suitability is not None
    assert projection.claims_suitability.status == ClaimsSuitabilityStatus.WEAK_CANDIDATE
    assert projection.claims_suitability.top_blockers == []
    assert any("rate-source" in reason for reason in projection.claims_suitability.top_reasons)
    assert any("rate-source" in action for action in projection.claims_suitability.recommended_next_actions)


def test_document_operations_claims_profile_blocks_downstream_action_gap() -> None:
    projection = derive_document_operations_readiness_inputs(
        _document_operations_profile(
            claims_profile=_claims_profile(
                downstream_action_approval_state=ClaimsReadinessState.MISSING,
            )
        )
    )

    assert projection.claims_suitability is not None
    assert projection.claims_suitability.status == ClaimsSuitabilityStatus.BLOCKED
    assert any("Downstream action approval" in blocker for blocker in projection.claims_suitability.top_blockers)


def test_document_operations_claims_profile_marks_savings_gap_as_weak_candidate() -> None:
    projection = derive_document_operations_readiness_inputs(
        _document_operations_profile(
            claims_profile=_claims_profile(
                savings_recognition_state=ClaimsReadinessState.REVIEW_REQUIRED,
            )
        )
    )

    assert projection.claims_suitability is not None
    assert projection.claims_suitability.status == ClaimsSuitabilityStatus.WEAK_CANDIDATE
    assert any("savings" in reason for reason in projection.claims_suitability.top_reasons)
