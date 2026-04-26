from __future__ import annotations

from scalescore.models.scaling import (
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


def derive_document_operations_readiness_inputs(
    profile: DocumentOperationsReadinessProfile,
) -> DocumentOperationsReadinessProjection:
    """Project document-operations snapshot signals into existing Readiness inputs."""

    return DocumentOperationsReadinessProjection(
        workflow_evidence=_derive_workflow_evidence(profile),
        operational_learning_inputs=_derive_operational_learning_inputs(profile),
        source_findings=_source_findings(profile),
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
    return OperationalLearningInputs(
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
    return findings


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
