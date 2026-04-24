from scalescore.core.operational_learning import score_operational_learning_suitability
from scalescore.models.scaling import (
    OperationalLearningCompletenessState,
    OperationalLearningGovernanceDependencyInput,
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


def test_score_operational_learning_marks_unsuitable_without_hard_blockers() -> None:
    result = score_operational_learning_suitability(
        OperationalLearningInputs(
            sop_reference_present=True,
            sop_clarity_signal=62.0,
            outcome_spec_present=True,
            outcome_observability_signal=61.0,
            repeatability_signal=55.0,
            review_path_present=True,
            review_density_signal=52.0,
            redaction_manageability_signal=65.0,
            governance_dependency_state=OperationalLearningGovernanceDependencyInput(
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
    assert result.governance_dependency_state.status == OperationalLearningGovernanceStateStatus.PARTIAL
    assert any("Repeatability" in reason for reason in result.top_reasons)
