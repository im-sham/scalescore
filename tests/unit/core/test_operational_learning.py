import pytest
from pydantic import ValidationError

from scalescore.core.operational_learning import score_operational_learning_suitability
from scalescore.models.scaling import (
    OperationalLearningCompletenessState,
    OperationalLearningGovernanceDependencyInput,
    OperationalLearningGovernanceDependencyState,
    OperationalLearningGovernanceStateStatus,
    OperationalLearningInputs,
    OperationalLearningSuitabilityStatus,
    RiskLevel,
)


def test_score_operational_learning_marks_training_candidate_when_signals_are_strong() -> None:
    result = score_operational_learning_suitability(
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
                evidence_basis="governance_owner_evidence",
                evidence_ref_id="governance-evidence-001",
                rights_completeness=OperationalLearningCompletenessState.COMPLETE,
                provenance_completeness=OperationalLearningCompletenessState.COMPLETE,
                redaction_readiness=OperationalLearningCompletenessState.COMPLETE,
                residual_risk_band=RiskLevel.LOW,
            ),
        )
    )

    assert result.status == OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE
    assert result.eval_suitability.status == OperationalLearningSuitabilityStatus.EVAL_SUITABLE
    assert (
        result.internal_training_candidacy.status
        == OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE
    )
    assert result.top_blockers == []
    assert result.eval_suitability.score >= 70.0
    assert result.internal_training_candidacy.score >= 80.0
    assert result.governance_dependency_state.status == OperationalLearningGovernanceStateStatus.READY
    assert result.governance_dependency_state.evidence_basis == "governance_owner_evidence"
    assert result.governance_dependency_state.evidence_ref_id == "governance-evidence-001"
    assert "Governance-owner evidence" in result.governance_dependency_state.summary


def test_complete_workflow_operator_review_can_be_eval_suitable_only() -> None:
    result = score_operational_learning_suitability(
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
                evidence_basis="workflow_operator_review",
                evidence_ref_id="workflow-review-001",
                rights_completeness=OperationalLearningCompletenessState.COMPLETE,
                provenance_completeness=OperationalLearningCompletenessState.COMPLETE,
                redaction_readiness=OperationalLearningCompletenessState.COMPLETE,
                residual_risk_band=RiskLevel.LOW,
            ),
        )
    )

    assert result.status == OperationalLearningSuitabilityStatus.EVAL_SUITABLE
    assert result.eval_suitability.threshold_met is True
    assert result.internal_training_candidacy.threshold_met is False
    assert result.governance_dependency_state.evidence_basis == "workflow_operator_review"
    assert result.governance_dependency_state.evidence_ref_id == "workflow-review-001"
    assert "Workflow-operator review" in result.governance_dependency_state.summary
    assert "not Governance approval or use authority" in result.governance_dependency_state.summary


@pytest.mark.parametrize(
    "model_type",
    [
        OperationalLearningGovernanceDependencyInput,
        OperationalLearningGovernanceDependencyState,
    ],
)
@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        (
            {
                "rights_completeness": "complete",
                "provenance_completeness": "complete",
                "redaction_readiness": "complete",
                "residual_risk_band": "low",
                "evidence_ref_id": "workflow-review-002",
            },
            "evidence_basis",
        ),
        (
            {
                "rights_completeness": "complete",
                "provenance_completeness": "complete",
                "redaction_readiness": "complete",
                "residual_risk_band": "low",
                "evidence_basis": "workflow_operator_review",
            },
            "evidence_ref_id",
        ),
        (
            {
                "rights_completeness": "complete",
                "evidence_basis": "workflow_operator_review",
                "evidence_ref_id": "   ",
            },
            "evidence_ref_id",
        ),
        (
            {
                "rights_completeness": "complete",
                "evidence_basis": "unattributed_review",
                "evidence_ref_id": "workflow-review-003",
            },
            "evidence_basis",
        ),
        (
            {"evidence_basis": "workflow_operator_review"},
            "evidence_ref_id",
        ),
        (
            {"evidence_ref_id": "workflow-review-orphan"},
            "evidence_basis",
        ),
    ],
)
def test_governance_dependency_fields_require_valid_evidence_attribution(
    model_type: type[
        OperationalLearningGovernanceDependencyInput
        | OperationalLearningGovernanceDependencyState
    ],
    payload: dict[str, str],
    missing_field: str,
) -> None:
    with pytest.raises(ValidationError, match=missing_field):
        model_type.model_validate(payload)


def test_workflow_operator_review_with_high_residual_risk_remains_blocked() -> None:
    result = score_operational_learning_suitability(
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
                evidence_basis="workflow_operator_review",
                evidence_ref_id="workflow-review-high-risk",
                rights_completeness=OperationalLearningCompletenessState.COMPLETE,
                provenance_completeness=OperationalLearningCompletenessState.COMPLETE,
                redaction_readiness=OperationalLearningCompletenessState.COMPLETE,
                residual_risk_band=RiskLevel.HIGH,
            ),
        )
    )

    assert result.status == OperationalLearningSuitabilityStatus.BLOCKED
    assert (
        result.governance_dependency_state.status
        == OperationalLearningGovernanceStateStatus.HIGH_RISK
    )
    assert "Workflow-operator review" in result.governance_dependency_state.summary


def test_workflow_operator_review_with_incomplete_evidence_remains_blocked() -> None:
    result = score_operational_learning_suitability(
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
                evidence_basis="workflow_operator_review",
                evidence_ref_id="workflow-review-incomplete",
                rights_completeness=OperationalLearningCompletenessState.COMPLETE,
                provenance_completeness=OperationalLearningCompletenessState.COMPLETE,
                redaction_readiness=OperationalLearningCompletenessState.MISSING,
                residual_risk_band=RiskLevel.LOW,
            ),
        )
    )

    assert result.status == OperationalLearningSuitabilityStatus.BLOCKED
    assert (
        result.governance_dependency_state.status
        == OperationalLearningGovernanceStateStatus.INCOMPLETE
    )
    assert any("Workflow-operator review evidence" in item for item in result.top_blockers)


def test_score_operational_learning_marks_blocked_when_governance_prerequisites_are_missing() -> None:
    result = score_operational_learning_suitability(
        OperationalLearningInputs(
            sop_reference_present=True,
            sop_clarity_signal=74.0,
            outcome_spec_present=True,
            outcome_observability_signal=72.0,
            repeatability_signal=79.0,
            review_path_present=True,
            review_density_signal=68.0,
            redaction_manageability_signal=76.0,
        )
    )

    assert result.status == OperationalLearningSuitabilityStatus.BLOCKED
    assert result.eval_suitability.status == OperationalLearningSuitabilityStatus.BLOCKED
    assert result.internal_training_candidacy.status == OperationalLearningSuitabilityStatus.BLOCKED
    assert any("Governance dependency state is missing" in blocker for blocker in result.top_blockers)
    assert result.governance_dependency_state.status == OperationalLearningGovernanceStateStatus.INCOMPLETE


def test_score_operational_learning_marks_weak_candidate_without_hard_blockers() -> None:
    result = score_operational_learning_suitability(
        OperationalLearningInputs(
            sop_reference_present=True,
            sop_clarity_signal=58.0,
            outcome_spec_present=True,
            outcome_observability_signal=57.0,
            repeatability_signal=51.0,
            review_path_present=True,
            review_density_signal=48.0,
            redaction_manageability_signal=58.0,
            governance_dependency_state=OperationalLearningGovernanceDependencyInput(
                evidence_basis="governance_owner_evidence",
                evidence_ref_id="governance-evidence-partial",
                rights_completeness=OperationalLearningCompletenessState.PARTIAL,
                provenance_completeness=OperationalLearningCompletenessState.PARTIAL,
                redaction_readiness=OperationalLearningCompletenessState.PARTIAL,
                residual_risk_band=RiskLevel.MEDIUM,
            ),
        )
    )

    assert result.status == OperationalLearningSuitabilityStatus.WEAK_CANDIDATE
    assert result.eval_suitability.status == OperationalLearningSuitabilityStatus.WEAK_CANDIDATE
    assert (
        result.internal_training_candidacy.status
        == OperationalLearningSuitabilityStatus.WEAK_CANDIDATE
    )
    assert result.top_blockers == []
    assert result.governance_dependency_state.status == OperationalLearningGovernanceStateStatus.PARTIAL
    assert any("Repeatability" in reason for reason in result.top_reasons)


def test_score_operational_learning_marks_unsuitable_when_non_blocked_signals_are_too_weak() -> None:
    result = score_operational_learning_suitability(
        OperationalLearningInputs(
            sop_reference_present=True,
            sop_clarity_signal=42.0,
            outcome_spec_present=True,
            outcome_observability_signal=43.0,
            repeatability_signal=39.0,
            review_path_present=True,
            review_density_signal=41.0,
            redaction_manageability_signal=45.0,
            governance_dependency_state=OperationalLearningGovernanceDependencyInput(
                evidence_basis="governance_owner_evidence",
                evidence_ref_id="governance-evidence-weak",
                rights_completeness=OperationalLearningCompletenessState.PARTIAL,
                provenance_completeness=OperationalLearningCompletenessState.PARTIAL,
                redaction_readiness=OperationalLearningCompletenessState.PARTIAL,
                residual_risk_band=RiskLevel.MEDIUM,
            ),
        )
    )

    assert result.status == OperationalLearningSuitabilityStatus.UNSUITABLE
    assert result.eval_suitability.status == OperationalLearningSuitabilityStatus.UNSUITABLE
    assert result.internal_training_candidacy.status == OperationalLearningSuitabilityStatus.UNSUITABLE
    assert result.top_blockers == []
