from __future__ import annotations

from scalescore.models.scaling import (
    ClaimsReadinessState,
    ClaimsSuitabilityStatus,
    ClaimsSuitabilitySummary,
    ClaimsWorkflowReadinessProfile,
    DocumentOperationsReadinessProfile,
    DocumentOperationsReadinessProjection,
    OperationalLearningCompletenessState,
    OperationalLearningGovernanceDependencyInput,
    OperationalLearningInputs,
    WorkflowControlCoverageInput,
    WorkflowControlStatus,
    WorkflowEvidenceInput,
    WorkflowEvidencePostureInput,
)

_CLAIMS_REQUIRED_EVIDENCE_CLASSES = {
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
}

_CLAIMS_CORE_EVIDENCE_CLASSES = {
    "claim_packet",
    "claim_line",
    "specialist_review_note",
}

_CLAIMS_READY_STATES = {
    ClaimsReadinessState.READY,
    ClaimsReadinessState.REVIEWED,
    ClaimsReadinessState.APPROVED,
}

_CLAIMS_BLOCKING_STATES = {
    ClaimsReadinessState.MISSING,
    ClaimsReadinessState.BLOCKED,
}


def derive_document_operations_readiness_inputs(
    profile: DocumentOperationsReadinessProfile,
) -> DocumentOperationsReadinessProjection:
    """Project document-operations snapshot signals into existing Readiness inputs."""

    return DocumentOperationsReadinessProjection(
        workflow_evidence=_derive_workflow_evidence(profile),
        operational_learning_inputs=_derive_operational_learning_inputs(profile),
        source_findings=_source_findings(profile),
        claims_suitability=_score_claims_suitability(profile.claims_profile),
    )


def _derive_workflow_evidence(
    profile: DocumentOperationsReadinessProfile,
) -> WorkflowEvidenceInput:
    return WorkflowEvidenceInput(
        control_coverage=WorkflowControlCoverageInput(
            approval_gate=_verified_when(
                profile.exception_requires_compliance_signoff
                and profile.exception_case_escalated
            ),
            decision_logging=_verified_when(profile.evidence_refs_present),
            evidence_retention=_verified_when(
                profile.evidence_refs_present and profile.normal_case_closed_with_evidence
            ),
            exception_handling=_verified_when(profile.exception_case_escalated),
            periodic_review=(
                WorkflowControlStatus.DOCUMENTED
                if profile.review_sla_defined is True
                else WorkflowControlStatus.MISSING
                if profile.review_sla_defined is False
                else None
            ),
        ),
        evidence_posture=WorkflowEvidencePostureInput(
            control_evidence_coverage_percent=(
                profile.control_evidence_coverage_percent
                if profile.control_evidence_coverage_percent is not None
                else _derived_evidence_coverage(profile)
            ),
            freshest_evidence_age_days=profile.freshest_evidence_age_days,
            audit_trail_complete=_all_true(
                profile.evidence_refs_present,
                profile.normal_case_closed_with_evidence,
                profile.exception_case_escalated,
            ),
            linked_artifacts=_linked_artifacts_present(profile),
        ),
        owner_confirmed=profile.owner_confirmed,
        systems_verified=profile.systems_verified,
        escalation_tested=profile.exception_case_escalated,
        fallback_tested=None,
        override_reviewed=profile.exception_requires_compliance_signoff,
        approval_evidence_count=profile.source_evidence_ref_count,
        decision_log_count=profile.reviewed_case_count,
        rollback_tested=None,
    )


def _derive_operational_learning_inputs(
    profile: DocumentOperationsReadinessProfile,
) -> OperationalLearningInputs:
    inputs = OperationalLearningInputs(
        sop_reference_present=_any_true(
            profile.sop_refs_present,
            profile.required_document_rules_present,
        ),
        sop_clarity_signal=_sop_clarity_signal(profile),
        outcome_spec_present=profile.outcome_refs_present,
        outcome_observability_signal=_outcome_observability_signal(profile),
        run_frequency_per_week=profile.weekly_packet_volume,
        repeatability_signal=_repeatability_signal(profile),
        review_path_present=_any_true(
            profile.exception_case_escalated,
            profile.exception_requires_compliance_signoff,
        ),
        review_density_signal=_review_density_signal(profile),
        redaction_manageability_signal=_redaction_manageability_signal(profile),
        governance_dependency_state=profile.governance_dependency_state,
    )
    return _apply_claims_operational_learning_adjustments(inputs, profile.claims_profile)


def _source_findings(profile: DocumentOperationsReadinessProfile) -> list[str]:
    findings = [
        (
            "Document operations fixture "
            f"{profile.fixture_id} assessed as {profile.workflow_family}."
        )
    ]
    if profile.subject_key:
        findings.append(
            f"Document operations subject {profile.subject_type}:{profile.subject_key} was referenced."
        )
    if profile.normal_case_id or profile.normal_case_state:
        findings.append(
            "Normal case "
            f"{profile.normal_case_id or 'unspecified'}: "
            f"{profile.normal_case_state or 'state unspecified'}."
        )
    if profile.exception_case_id or profile.exception_case_state:
        findings.append(
            "Exception case "
            f"{profile.exception_case_id or 'unspecified'}: "
            f"{profile.exception_case_state or 'state unspecified'}."
        )
    if profile.redaction_review_required_before_internal_eval is True:
        findings.append("Internal-eval use depends on Governance redaction review.")
    claims_suitability = _score_claims_suitability(profile.claims_profile)
    if claims_suitability is not None:
        findings.append(f"Claims suitability status: {claims_suitability.status.value}.")
        findings.extend(claims_suitability.top_blockers[:2])
    return findings


def _score_claims_suitability(
    claims_profile: ClaimsWorkflowReadinessProfile | None,
) -> ClaimsSuitabilitySummary | None:
    if claims_profile is None:
        return None

    missing_evidence = sorted(
        _CLAIMS_REQUIRED_EVIDENCE_CLASSES - set(claims_profile.evidence_class_ids_present)
    )
    missing_core_evidence = [
        class_id for class_id in missing_evidence if class_id in _CLAIMS_CORE_EVIDENCE_CLASSES
    ]
    blockers: list[str] = []
    reasons: list[str] = []
    actions: list[str] = []
    score = 100.0

    if missing_evidence:
        penalty = 6.0 * len(missing_evidence)
        score -= penalty
        reasons.append(
            "Claims evidence map is missing "
            + ", ".join(missing_evidence[:4])
            + "."
        )
        actions.append("Complete the claims evidence map with synthetic ref summaries only.")
    if missing_core_evidence:
        blockers.append(
            "Core claims evidence classes are missing: "
            + ", ".join(missing_core_evidence)
            + "."
        )

    if not _claims_state_ready(claims_profile.source_readiness_state):
        score -= 20.0
        blockers.append("Claims source readiness is not ready.")
        actions.append("Confirm read-only source readiness before scoring claims launch suitability.")

    if not _claims_state_ready(claims_profile.phi_boundary_review_state):
        score -= 25.0
        blockers.append("PHI boundary review is not complete.")
        actions.append("Complete PHI boundary review with the implementation admin and compliance owner.")

    if not _claims_state_ready(claims_profile.redaction_review_state):
        score -= 25.0
        blockers.append("Claims redaction review is not complete.")
        actions.append("Complete redaction review before internal-eval suitability is considered.")

    if not _claims_state_ready(claims_profile.governance_claims_control_state):
        score -= 25.0
        blockers.append("Governance claims controls are not ready.")
        actions.append(
            "Complete Governance claims-control review for use approval, redaction, and control posture."
        )

    if not _claims_state_ready(claims_profile.downstream_action_approval_state):
        score -= 22.0
        blockers.append("Downstream action approval is missing or not ready.")
        actions.append("Confirm downstream action approval before launch-readiness claims.")

    if not _claims_state_ready(claims_profile.rate_source_review_state):
        score -= 18.0
        reasons.append("Claims rate-source traceability is not reviewed.")
        actions.append("Confirm rate-source license, version, lookup method, and storage posture.")

    if not _claims_state_ready(claims_profile.downstream_consistency_state):
        score -= 14.0
        if _claims_state_blocking(claims_profile.downstream_consistency_state):
            blockers.append("Downstream consistency evidence is blocked or missing.")
        else:
            reasons.append("Downstream consistency is still awaiting review.")
        actions.append("Map destination, export digest, acknowledgement state, and owner checkpoint.")

    if not _claims_state_ready(claims_profile.savings_recognition_state):
        score -= 14.0
        if _claims_state_blocking(claims_profile.savings_recognition_state):
            reasons.append("Claims savings recognition evidence is missing.")
        else:
            reasons.append("Claims savings recognition remains under review.")
        actions.append("Define baseline, accepted outcome, recognition event, and finance owner.")

    bounded_score = _bounded_score(score)
    unique_blockers = _unique_items(blockers)
    if unique_blockers:
        status = ClaimsSuitabilityStatus.BLOCKED
    elif bounded_score >= 80.0 and not reasons:
        status = ClaimsSuitabilityStatus.EVAL_SUITABLE
    elif bounded_score >= 50.0:
        status = ClaimsSuitabilityStatus.WEAK_CANDIDATE
    else:
        status = ClaimsSuitabilityStatus.BLOCKED

    if status == ClaimsSuitabilityStatus.EVAL_SUITABLE and not reasons:
        reasons.append(
            "Synthetic claims profile has reviewed PHI/redaction, rate-source, downstream, "
            "savings, source, and Governance dependency posture."
        )

    return ClaimsSuitabilitySummary(
        profile_id=claims_profile.profile_id,
        status=status,
        score=bounded_score,
        top_blockers=unique_blockers[:5],
        top_reasons=_unique_items(reasons)[:5],
        recommended_next_actions=_unique_items(actions)[:5],
        governance_dependency_state=_state_bucket(
            claims_profile.governance_claims_control_state
        ),
        evidence_gap_state="ready" if not missing_evidence else "missing",
        phi_redaction_state=_phi_redaction_state(claims_profile),
        rate_source_traceability_state=_state_bucket(
            claims_profile.rate_source_review_state
        ),
        downstream_consistency_state=_downstream_state(claims_profile),
        savings_lifecycle_state=_state_bucket(
            claims_profile.savings_recognition_state
        ),
    )


def _apply_claims_operational_learning_adjustments(
    inputs: OperationalLearningInputs,
    claims_profile: ClaimsWorkflowReadinessProfile | None,
) -> OperationalLearningInputs:
    if claims_profile is None:
        return inputs

    updates: dict[str, object] = {}
    if not _claims_state_ready(claims_profile.phi_boundary_review_state) or not _claims_state_ready(
        claims_profile.redaction_review_state
    ):
        current_signal = inputs.redaction_manageability_signal
        updates["redaction_manageability_signal"] = (
            30.0 if current_signal is None else min(current_signal, 30.0)
        )

    return inputs.model_copy(update=updates) if updates else inputs


def _claims_state_ready(state: ClaimsReadinessState | None) -> bool:
    return state in _CLAIMS_READY_STATES


def _claims_state_blocking(state: ClaimsReadinessState | None) -> bool:
    return state is None or state in _CLAIMS_BLOCKING_STATES


def _state_bucket(state: ClaimsReadinessState | None) -> str:
    if _claims_state_ready(state):
        return "ready"
    if _claims_state_blocking(state):
        return "blocked"
    return "review_required"


def _phi_redaction_state(claims_profile: ClaimsWorkflowReadinessProfile) -> str:
    states = [
        claims_profile.phi_boundary_review_state,
        claims_profile.redaction_review_state,
    ]
    if all(_claims_state_ready(state) for state in states):
        return "ready"
    if any(_claims_state_blocking(state) for state in states):
        return "blocked"
    return "review_required"


def _downstream_state(claims_profile: ClaimsWorkflowReadinessProfile) -> str:
    states = [
        claims_profile.downstream_consistency_state,
        claims_profile.downstream_action_approval_state,
    ]
    if all(_claims_state_ready(state) for state in states):
        return "ready"
    if any(_claims_state_blocking(state) for state in states):
        return "blocked"
    return "review_required"


def _verified_when(value: bool | None) -> WorkflowControlStatus | None:
    if value is True:
        return WorkflowControlStatus.VERIFIED
    if value is False:
        return WorkflowControlStatus.MISSING
    return None


def _all_true(*values: bool | None) -> bool | None:
    if any(value is None for value in values):
        return None
    return all(value is True for value in values)


def _any_true(*values: bool | None) -> bool | None:
    if any(value is True for value in values):
        return True
    if all(value is False for value in values):
        return False
    return None


def _linked_artifacts_present(
    profile: DocumentOperationsReadinessProfile,
) -> bool | None:
    if profile.source_evidence_ref_count is not None:
        return profile.source_evidence_ref_count > 0
    return profile.evidence_refs_present


def _derived_evidence_coverage(
    profile: DocumentOperationsReadinessProfile,
) -> float | None:
    checks = [
        profile.sop_refs_present,
        profile.outcome_refs_present,
        profile.required_document_rules_present,
        profile.evidence_refs_present,
        profile.normal_case_closed_with_evidence,
        profile.exception_case_escalated,
        profile.exception_requires_compliance_signoff,
    ]
    known_checks = [value for value in checks if value is not None]
    if not known_checks:
        return None
    return round(sum(1 for value in known_checks if value) / len(known_checks) * 100.0, 1)


def _sop_clarity_signal(profile: DocumentOperationsReadinessProfile) -> float | None:
    if profile.sop_refs_present is None and profile.required_document_rules_present is None:
        return None
    if profile.sop_refs_present is True and profile.required_document_rules_present is True:
        return 84.0
    if profile.sop_refs_present is True or profile.required_document_rules_present is True:
        return 64.0
    return 30.0


def _outcome_observability_signal(
    profile: DocumentOperationsReadinessProfile,
) -> float | None:
    checks = [
        profile.outcome_refs_present,
        profile.evidence_refs_present,
        profile.normal_case_closed_with_evidence,
        profile.exception_case_escalated,
    ]
    known_checks = [value for value in checks if value is not None]
    if not known_checks:
        return None
    ratio = sum(1 for value in known_checks if value) / len(known_checks)
    return round(35.0 + ratio * 53.0, 1)


def _repeatability_signal(profile: DocumentOperationsReadinessProfile) -> float | None:
    if profile.weekly_packet_volume is None:
        return None
    volume = profile.weekly_packet_volume
    if volume >= 50.0:
        base = 88.0
    elif volume >= 20.0:
        base = 80.0
    elif volume >= 5.0:
        base = 68.0
    elif volume > 0.0:
        base = 55.0
    else:
        base = 25.0
    if profile.required_document_rules_present is False:
        base -= 12.0
    elif profile.required_document_rules_present is True:
        base += 2.0
    return _bounded_score(base)


def _review_density_signal(profile: DocumentOperationsReadinessProfile) -> float | None:
    if profile.reviewed_case_count is None:
        return None
    count = profile.reviewed_case_count
    if count >= 25:
        base = 80.0
    elif count >= 10:
        base = 70.0
    elif count >= 3:
        base = 56.0
    elif count > 0:
        base = 45.0
    else:
        base = 25.0
    if profile.exception_case_escalated is True:
        base += 3.0
    if profile.exception_requires_compliance_signoff is True:
        base += 2.0
    return _bounded_score(base)


def _redaction_manageability_signal(
    profile: DocumentOperationsReadinessProfile,
) -> float | None:
    if profile.redaction_review_required_before_internal_eval is False:
        return 35.0
    governance = profile.governance_dependency_state
    redaction_state = (
        governance.redaction_readiness
        if isinstance(governance, OperationalLearningGovernanceDependencyInput)
        else None
    )
    if redaction_state == OperationalLearningCompletenessState.COMPLETE:
        return 82.0
    if redaction_state == OperationalLearningCompletenessState.PARTIAL:
        return 65.0
    if redaction_state == OperationalLearningCompletenessState.MISSING:
        return 35.0
    if profile.redaction_review_required_before_internal_eval is True:
        return 50.0
    return None


def _bounded_score(score: float) -> float:
    return round(max(0.0, min(100.0, score)), 1)


def _unique_items(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
