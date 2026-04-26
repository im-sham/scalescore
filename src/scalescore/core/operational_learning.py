from __future__ import annotations

from scalescore.models.scaling import (
    OperationalLearningAssessmentResult,
    OperationalLearningCompletenessState,
    OperationalLearningDimension,
    OperationalLearningDimensionScore,
    OperationalLearningGovernanceDependencyInput,
    OperationalLearningGovernanceDependencyState,
    OperationalLearningGovernanceStateStatus,
    OperationalLearningInputs,
    OperationalLearningSuitabilityStatus,
    OperationalLearningSuitabilitySummary,
    RiskLevel,
    ScaleScoreReport,
)

_EVAL_THRESHOLD = 70.0
_TRAINING_THRESHOLD = 80.0

_EVAL_WEIGHTS: dict[OperationalLearningDimension, float] = {
    OperationalLearningDimension.REPEATABILITY: 25.0,
    OperationalLearningDimension.SOP_CLARITY: 20.0,
    OperationalLearningDimension.OUTCOME_OBSERVABILITY: 20.0,
    OperationalLearningDimension.REVIEW_DENSITY: 15.0,
    OperationalLearningDimension.REDACTION_MANAGEABILITY: 10.0,
    OperationalLearningDimension.GOVERNANCE_SAFETY: 10.0,
}

_TRAINING_WEIGHTS: dict[OperationalLearningDimension, float] = {
    OperationalLearningDimension.REPEATABILITY: 20.0,
    OperationalLearningDimension.SOP_CLARITY: 15.0,
    OperationalLearningDimension.OUTCOME_OBSERVABILITY: 15.0,
    OperationalLearningDimension.REVIEW_DENSITY: 15.0,
    OperationalLearningDimension.REDACTION_MANAGEABILITY: 20.0,
    OperationalLearningDimension.GOVERNANCE_SAFETY: 15.0,
}

_COMPLETENESS_SCORE: dict[OperationalLearningCompletenessState, float] = {
    OperationalLearningCompletenessState.COMPLETE: 92.0,
    OperationalLearningCompletenessState.PARTIAL: 65.0,
    OperationalLearningCompletenessState.MISSING: 25.0,
}

_REDACTION_READINESS_SCORE: dict[OperationalLearningCompletenessState, float] = {
    OperationalLearningCompletenessState.COMPLETE: 80.0,
    OperationalLearningCompletenessState.PARTIAL: 55.0,
    OperationalLearningCompletenessState.MISSING: 25.0,
}

_RESIDUAL_RISK_SCORE: dict[RiskLevel, float] = {
    RiskLevel.LOW: 92.0,
    RiskLevel.MEDIUM: 75.0,
    RiskLevel.HIGH: 45.0,
    RiskLevel.CRITICAL: 20.0,
}


def apply_operational_learning_inputs(
    report: ScaleScoreReport,
    operational_learning_inputs: OperationalLearningInputs | None,
) -> ScaleScoreReport:
    """Attach additive operational-learning suitability to a workflow report."""

    if operational_learning_inputs is None or report.workflow_context is None:
        return report

    return report.model_copy(
        update={
            "operational_learning_suitability": score_operational_learning_suitability(
                operational_learning_inputs
            )
        }
    )


def score_operational_learning_suitability(
    inputs: OperationalLearningInputs,
) -> OperationalLearningSuitabilitySummary:
    """Score workflow suitability for internal eval and internal training candidacy."""

    governance_state = _build_governance_dependency_state(inputs.governance_dependency_state)
    dimension_scores = [
        _score_repeatability(inputs),
        _score_sop_clarity(inputs),
        _score_outcome_observability(inputs),
        _score_review_density(inputs),
        _score_redaction_manageability(inputs),
        _score_governance_safety(inputs, governance_state),
    ]
    score_by_dimension = {entry.dimension: entry.score for entry in dimension_scores}
    top_blockers = _top_blockers(inputs, score_by_dimension, governance_state)
    hard_blocked = bool(top_blockers)

    eval_score = _weighted_score(score_by_dimension, _EVAL_WEIGHTS)
    training_score = _weighted_score(score_by_dimension, _TRAINING_WEIGHTS)

    eval_threshold_met = (
        not hard_blocked
        and eval_score >= _EVAL_THRESHOLD
        and score_by_dimension[OperationalLearningDimension.REPEATABILITY] >= 60.0
        and score_by_dimension[OperationalLearningDimension.SOP_CLARITY] >= 60.0
        and score_by_dimension[OperationalLearningDimension.OUTCOME_OBSERVABILITY] >= 60.0
        and score_by_dimension[OperationalLearningDimension.REVIEW_DENSITY] >= 50.0
    )
    training_threshold_met = (
        not hard_blocked
        and eval_threshold_met
        and training_score >= _TRAINING_THRESHOLD
        and score_by_dimension[OperationalLearningDimension.REPEATABILITY] >= 75.0
        and score_by_dimension[OperationalLearningDimension.SOP_CLARITY] >= 70.0
        and score_by_dimension[OperationalLearningDimension.OUTCOME_OBSERVABILITY] >= 70.0
        and score_by_dimension[OperationalLearningDimension.REVIEW_DENSITY] >= 65.0
        and score_by_dimension[OperationalLearningDimension.REDACTION_MANAGEABILITY] >= 70.0
        and score_by_dimension[OperationalLearningDimension.GOVERNANCE_SAFETY] >= 60.0
    )
    weak_candidate = (
        not hard_blocked
        and not eval_threshold_met
        and eval_score >= 50.0
        and score_by_dimension[OperationalLearningDimension.REPEATABILITY] >= 45.0
        and score_by_dimension[OperationalLearningDimension.SOP_CLARITY] >= 45.0
        and score_by_dimension[OperationalLearningDimension.OUTCOME_OBSERVABILITY] >= 45.0
        and score_by_dimension[OperationalLearningDimension.REVIEW_DENSITY] >= 40.0
        and score_by_dimension[OperationalLearningDimension.REDACTION_MANAGEABILITY] >= 40.0
        and score_by_dimension[OperationalLearningDimension.GOVERNANCE_SAFETY] >= 35.0
    )

    if training_threshold_met:
        overall_status = OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE
    elif eval_threshold_met:
        overall_status = OperationalLearningSuitabilityStatus.EVAL_SUITABLE
    elif hard_blocked:
        overall_status = OperationalLearningSuitabilityStatus.BLOCKED
    elif weak_candidate:
        overall_status = OperationalLearningSuitabilityStatus.WEAK_CANDIDATE
    else:
        overall_status = OperationalLearningSuitabilityStatus.UNSUITABLE

    eval_status = (
        OperationalLearningSuitabilityStatus.BLOCKED
        if hard_blocked
        else (
            OperationalLearningSuitabilityStatus.EVAL_SUITABLE
            if eval_threshold_met
            else OperationalLearningSuitabilityStatus.WEAK_CANDIDATE
            if weak_candidate
            else OperationalLearningSuitabilityStatus.UNSUITABLE
        )
    )
    training_status = (
        OperationalLearningSuitabilityStatus.BLOCKED
        if hard_blocked
        else (
            OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE
            if training_threshold_met
            else OperationalLearningSuitabilityStatus.WEAK_CANDIDATE
            if weak_candidate
            else OperationalLearningSuitabilityStatus.UNSUITABLE
        )
    )

    return OperationalLearningSuitabilitySummary(
        status=overall_status,
        dimension_scores=dimension_scores,
        eval_suitability=OperationalLearningAssessmentResult(
            score=eval_score,
            status=eval_status,
            threshold=_EVAL_THRESHOLD,
            threshold_met=eval_threshold_met,
            hard_blocked=hard_blocked,
        ),
        internal_training_candidacy=OperationalLearningAssessmentResult(
            score=training_score,
            status=training_status,
            threshold=_TRAINING_THRESHOLD,
            threshold_met=training_threshold_met,
            hard_blocked=hard_blocked,
        ),
        top_blockers=top_blockers,
        top_reasons=_top_reasons(dimension_scores, overall_status),
        recommended_next_actions=_recommended_next_actions(
            inputs, score_by_dimension, governance_state
        ),
        governance_dependency_state=governance_state,
    )


def _score_repeatability(inputs: OperationalLearningInputs) -> OperationalLearningDimensionScore:
    if inputs.repeatability_signal is not None:
        score = inputs.repeatability_signal
        rationale = "Explicit repeatability signal was supplied from upstream workflow inputs."
    elif inputs.run_frequency_per_week is None:
        score = 45.0
        rationale = "Run frequency or repeatability signal was not supplied for this workflow."
    else:
        frequency = inputs.run_frequency_per_week
        if frequency >= 10.0:
            score = 90.0
        elif frequency >= 5.0:
            score = 80.0
        elif frequency >= 3.0:
            score = 70.0
        elif frequency >= 1.0:
            score = 60.0
        elif frequency > 0.0:
            score = 45.0
        else:
            score = 25.0
        rationale = (
            f"Observed run frequency of {frequency:g} per week was used as the repeatability signal."
        )

    return OperationalLearningDimensionScore(
        dimension=OperationalLearningDimension.REPEATABILITY,
        score=_bounded_score(score),
        rationale=rationale,
    )


def _score_sop_clarity(inputs: OperationalLearningInputs) -> OperationalLearningDimensionScore:
    return _score_presence_or_signal(
        dimension=OperationalLearningDimension.SOP_CLARITY,
        signal=inputs.sop_clarity_signal,
        present=inputs.sop_reference_present,
        present_score=65.0,
        explicit_rationale="Explicit SOP clarity signal was supplied from upstream workflow inputs.",
        present_rationale="A linked SOP reference is present, but no separate clarity signal was supplied.",
        missing_rationale="No linked SOP reference or SOP clarity signal was supplied.",
    )


def _score_outcome_observability(
    inputs: OperationalLearningInputs,
) -> OperationalLearningDimensionScore:
    return _score_presence_or_signal(
        dimension=OperationalLearningDimension.OUTCOME_OBSERVABILITY,
        signal=inputs.outcome_observability_signal,
        present=inputs.outcome_spec_present,
        present_score=65.0,
        explicit_rationale=(
            "Explicit outcome observability signal was supplied from upstream workflow inputs."
        ),
        present_rationale=(
            "An outcome specification is present, but no separate observability signal was supplied."
        ),
        missing_rationale="No outcome specification or observability signal was supplied.",
    )


def _score_review_density(inputs: OperationalLearningInputs) -> OperationalLearningDimensionScore:
    return _score_presence_or_signal(
        dimension=OperationalLearningDimension.REVIEW_DENSITY,
        signal=inputs.review_density_signal,
        present=inputs.review_path_present,
        present_score=55.0,
        explicit_rationale="Explicit review-density signal was supplied from upstream workflow inputs.",
        present_rationale="A review path is present, but no separate review-density signal was supplied.",
        missing_rationale="No review path or review-density signal was supplied.",
    )


def _score_redaction_manageability(
    inputs: OperationalLearningInputs,
) -> OperationalLearningDimensionScore:
    if inputs.redaction_manageability_signal is not None:
        score = inputs.redaction_manageability_signal
        rationale = (
            "Explicit redaction-manageability signal was supplied from upstream workflow inputs."
        )
    elif (
        inputs.governance_dependency_state is not None
        and inputs.governance_dependency_state.redaction_readiness is not None
    ):
        readiness = inputs.governance_dependency_state.redaction_readiness
        score = _REDACTION_READINESS_SCORE[readiness]
        rationale = {
            OperationalLearningCompletenessState.COMPLETE: (
                "Governance dependency inputs indicate redaction readiness is complete."
            ),
            OperationalLearningCompletenessState.PARTIAL: (
                "Governance dependency inputs indicate redaction readiness is only partial."
            ),
            OperationalLearningCompletenessState.MISSING: (
                "Governance dependency inputs indicate redaction readiness is still missing."
            ),
        }[readiness]
    else:
        score = 35.0
        rationale = "Redaction manageability signal was not supplied."

    return OperationalLearningDimensionScore(
        dimension=OperationalLearningDimension.REDACTION_MANAGEABILITY,
        score=_bounded_score(score),
        rationale=rationale,
    )


def _score_governance_safety(
    inputs: OperationalLearningInputs,
    governance_state: OperationalLearningGovernanceDependencyState,
) -> OperationalLearningDimensionScore:
    governance_input = inputs.governance_dependency_state
    if governance_input is None:
        score = 25.0
    else:
        component_scores = [
            _COMPLETENESS_SCORE.get(governance_input.rights_completeness, 25.0),
            _COMPLETENESS_SCORE.get(governance_input.provenance_completeness, 25.0),
            _COMPLETENESS_SCORE.get(governance_input.redaction_readiness, 25.0),
            _RESIDUAL_RISK_SCORE.get(governance_input.residual_risk_band, 25.0),
        ]
        score = sum(component_scores) / len(component_scores)

    return OperationalLearningDimensionScore(
        dimension=OperationalLearningDimension.GOVERNANCE_SAFETY,
        score=_bounded_score(score),
        rationale=governance_state.summary,
    )


def _score_presence_or_signal(
    *,
    dimension: OperationalLearningDimension,
    signal: float | None,
    present: bool | None,
    present_score: float,
    explicit_rationale: str,
    present_rationale: str,
    missing_rationale: str,
) -> OperationalLearningDimensionScore:
    if signal is not None:
        score = signal
        rationale = explicit_rationale
    elif present is True:
        score = present_score
        rationale = present_rationale
    else:
        score = 25.0 if present is None else 20.0
        rationale = missing_rationale

    return OperationalLearningDimensionScore(
        dimension=dimension,
        score=_bounded_score(score),
        rationale=rationale,
    )


def _build_governance_dependency_state(
    governance_input: OperationalLearningGovernanceDependencyInput | None,
) -> OperationalLearningGovernanceDependencyState:
    if governance_input is None:
        return OperationalLearningGovernanceDependencyState(
            status=OperationalLearningGovernanceStateStatus.INCOMPLETE,
            summary="Governance dependency state was not supplied for operational-learning scoring.",
        )

    incomplete_labels = _governance_incomplete_labels(governance_input)
    partial_labels = _governance_partial_labels(governance_input)

    if incomplete_labels:
        summary = (
            "Governance dependency state is incomplete for "
            + ", ".join(incomplete_labels)
            + "."
        )
        status = OperationalLearningGovernanceStateStatus.INCOMPLETE
    elif governance_input.residual_risk_band in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        summary = (
            "Governance dependency state is present, but residual risk remains "
            f"{governance_input.residual_risk_band.value}."
        )
        status = OperationalLearningGovernanceStateStatus.HIGH_RISK
    elif partial_labels:
        summary = (
            "Governance dependency state is partially complete for "
            + ", ".join(partial_labels)
            + "."
        )
        status = OperationalLearningGovernanceStateStatus.PARTIAL
    else:
        summary = (
            "Governance dependency state is complete with residual risk "
            f"{governance_input.residual_risk_band.value}."
        )
        status = OperationalLearningGovernanceStateStatus.READY

    return OperationalLearningGovernanceDependencyState(
        rights_completeness=governance_input.rights_completeness,
        provenance_completeness=governance_input.provenance_completeness,
        redaction_readiness=governance_input.redaction_readiness,
        residual_risk_band=governance_input.residual_risk_band,
        status=status,
        summary=summary,
    )


def _top_blockers(
    inputs: OperationalLearningInputs,
    score_by_dimension: dict[OperationalLearningDimension, float],
    governance_state: OperationalLearningGovernanceDependencyState,
) -> list[str]:
    blockers: list[str] = []

    if not _has_prerequisite(inputs.sop_reference_present, inputs.sop_clarity_signal):
        blockers.append("Missing SOP reference or SOP clarity prerequisite.")
    if not _has_prerequisite(
        inputs.outcome_spec_present,
        inputs.outcome_observability_signal,
    ):
        blockers.append("Missing outcome specification or observability signal.")
    if not _has_prerequisite(inputs.review_path_present, inputs.review_density_signal):
        blockers.append("Missing review path or review-density signal.")

    governance_input = inputs.governance_dependency_state
    if governance_input is None:
        blockers.append("Governance dependency state is missing where required.")
    else:
        incomplete_labels = _governance_incomplete_labels(governance_input)
        if incomplete_labels:
            blockers.append(
                "Governance prerequisites remain incomplete for "
                + ", ".join(incomplete_labels)
                + "."
            )

    if score_by_dimension[OperationalLearningDimension.REDACTION_MANAGEABILITY] < 40.0:
        blockers.append("Redaction manageability is below the minimum floor for learning use.")
    if score_by_dimension[OperationalLearningDimension.GOVERNANCE_SAFETY] < 35.0:
        blockers.append("Governance safety is below the minimum floor for learning use.")
    if governance_state.status == OperationalLearningGovernanceStateStatus.HIGH_RISK:
        blockers.append(
            "Residual governance risk remains too high for operational-learning candidacy."
        )

    return _unique_items(blockers)[:3]


def _top_reasons(
    dimension_scores: list[OperationalLearningDimensionScore],
    overall_status: OperationalLearningSuitabilityStatus,
) -> list[str]:
    reverse = overall_status in {
        OperationalLearningSuitabilityStatus.EVAL_SUITABLE,
        OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE,
    }
    ordered = sorted(dimension_scores, key=lambda entry: entry.score, reverse=reverse)
    return [
        f"{_humanize_dimension(entry.dimension)}: {entry.rationale}"
        for entry in ordered[:3]
    ]


def _recommended_next_actions(
    inputs: OperationalLearningInputs,
    score_by_dimension: dict[OperationalLearningDimension, float],
    governance_state: OperationalLearningGovernanceDependencyState,
) -> list[str]:
    actions: list[str] = []

    if not _has_prerequisite(inputs.sop_reference_present, inputs.sop_clarity_signal):
        actions.append(
            "Link a current SOP or runbook reference, or provide an explicit SOP clarity signal."
        )
    elif score_by_dimension[OperationalLearningDimension.SOP_CLARITY] < 60.0:
        actions.append("Tighten the SOP so the workflow steps are clear enough for internal eval use.")

    if not _has_prerequisite(
        inputs.outcome_spec_present,
        inputs.outcome_observability_signal,
    ):
        actions.append(
            "Define the expected outcome specification and provide an observability signal."
        )
    elif score_by_dimension[OperationalLearningDimension.OUTCOME_OBSERVABILITY] < 60.0:
        actions.append("Make workflow outcomes easier to observe and score against an expected result.")

    if not _has_prerequisite(inputs.review_path_present, inputs.review_density_signal):
        actions.append("Document the review path and capture reviewed workflow examples.")
    elif score_by_dimension[OperationalLearningDimension.REVIEW_DENSITY] < 65.0:
        actions.append("Increase review density so the workflow can support higher-confidence learning assets.")

    if score_by_dimension[OperationalLearningDimension.REPEATABILITY] < 60.0:
        actions.append("Collect stronger repeatability evidence from run frequency or repeated cases.")

    if score_by_dimension[OperationalLearningDimension.REDACTION_MANAGEABILITY] < 40.0:
        actions.append(
            "Reduce redaction burden or prove a safer transform path before using this workflow for learning."
        )
    elif score_by_dimension[OperationalLearningDimension.REDACTION_MANAGEABILITY] < 70.0:
        actions.append(
            "Improve redaction manageability before considering the workflow for internal training candidacy."
        )

    if governance_state.status != OperationalLearningGovernanceStateStatus.READY or (
        score_by_dimension[OperationalLearningDimension.GOVERNANCE_SAFETY] < 60.0
    ):
        actions.append(
            "Complete governance dependency review for rights, provenance, redaction readiness, and residual risk."
        )

    return _unique_items(actions)[:3]


def _has_prerequisite(present: bool | None, signal: float | None) -> bool:
    return present is True or signal is not None


def _governance_incomplete_labels(
    governance_input: OperationalLearningGovernanceDependencyInput,
) -> list[str]:
    labels: list[str] = []
    for label, value in (
        ("rights completeness", governance_input.rights_completeness),
        ("provenance completeness", governance_input.provenance_completeness),
        ("redaction readiness", governance_input.redaction_readiness),
    ):
        if value is None or value == OperationalLearningCompletenessState.MISSING:
            labels.append(label)
    if governance_input.residual_risk_band is None:
        labels.append("residual risk band")
    return labels


def _governance_partial_labels(
    governance_input: OperationalLearningGovernanceDependencyInput,
) -> list[str]:
    return [
        label
        for label, value in (
            ("rights completeness", governance_input.rights_completeness),
            ("provenance completeness", governance_input.provenance_completeness),
            ("redaction readiness", governance_input.redaction_readiness),
        )
        if value == OperationalLearningCompletenessState.PARTIAL
    ]


def _weighted_score(
    score_by_dimension: dict[OperationalLearningDimension, float],
    weights: dict[OperationalLearningDimension, float],
) -> float:
    weighted_sum = sum(score_by_dimension[dimension] * weight for dimension, weight in weights.items())
    return round(weighted_sum / sum(weights.values()), 1)


def _humanize_dimension(dimension: OperationalLearningDimension) -> str:
    return dimension.value.replace("_", " ").title()


def _bounded_score(score: float) -> float:
    return round(max(0.0, min(100.0, score)), 1)


def _unique_items(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
