from datetime import UTC, datetime

import pytest

from scalescore.core.assessment import run_workflow_assessment
from scalescore.core.exceptions import ErrorCode, ScaleScoreError
from scalescore.models.scaling import (
    AssessmentMode,
    LegacyWorkflowRef,
    LegacyWorkflowRefEnvelope,
    ScaleScoreReport,
    WorkflowAssessmentContext,
    WorkflowBlastRadius,
    WorkflowReadinessPillar,
)


def _workflow_report(
    *, owner: str = "Operations Lead", with_refs: bool = False
) -> ScaleScoreReport:
    workflow_ref = (
        LegacyWorkflowRefEnvelope(
            issued_at="2026-08-13T12:00:00Z",
            ref=LegacyWorkflowRef(
                ref_id="workflow:tenant-a:wf-support",
                organization_id="tenant-a",
                external_uri="/api/workflows/wf-support",
                snapshot_id="snapshot-1",
                version="version-1",
                created_at="2026-08-13T12:00:00Z",
                updated_at="2026-08-13T12:00:00Z",
                summary="Support workflow pointer",
                workflow_id="wf-support",
                title="Support Triage",
                subject_type="workflow",
                owner="Operations Lead",
                review_status="reviewed",
            ),
        )
        if with_refs
        else None
    )
    report = run_workflow_assessment(
        org_id="tenant-a",
        org_name="Tenant A",
        workflow_context=WorkflowAssessmentContext(
            workflow_id="wf-support",
            name="Support Triage",
            business_function="support",
            owner=owner,
            ai_role="Triage inbound work",
            systems_touched=["ticketing"],
            human_escalation_path=["support-lead"],
            control_requirements=["decision logging"],
            blast_radius=WorkflowBlastRadius.MEDIUM,
            fallback_mode="Manual triage",
            override_rights=["support-lead"],
            error_tolerance="Low",
            reversibility="Tickets can be reassigned",
        ),
        baseline_operational_score=78.0,
        source_findings=["EXCLUDED_SOURCE_FINDING"],
        workflow_ref=workflow_ref,
    )
    return report.model_copy(
        update={
            "generated_at": datetime(2026, 8, 13, 12, 30, tzinfo=UTC),
            "workflow_pillar_scores": list(reversed(report.workflow_pillar_scores)),
            "top_trust_gaps": ["First trust gap", "Second trust gap"],
            "prioritized_remediation_actions": ["First action", "Second action"],
            "executive_summary": "EXCLUDED_EXECUTIVE_SUMMARY",
            "key_findings": ["EXCLUDED_SOURCE_FINDING"],
            "immediate_actions": ["EXCLUDED_UNRELATED_ACTION"],
        }
    )


def test_operator_summary_is_exact_ordered_allowlisted_projection() -> None:
    from scalescore.core.operator_summary import build_operator_summary

    report = _workflow_report()

    payload = build_operator_summary(report).model_dump(mode="json", exclude_none=True)

    assert list(payload) == [
        "assessment_id",
        "workflow_id",
        "workflow_name",
        "accountable_owner",
        "readiness_score",
        "readiness_grade",
        "pillars",
        "top_trust_gaps",
        "remediation_actions",
        "source_assessment_generated_at",
        "diagnostic_only",
        "no_decision_authority",
    ]
    assert payload["assessment_id"] == report.report_id
    assert payload["workflow_id"] == "wf-support"
    assert payload["workflow_name"] == "Support Triage"
    assert payload["accountable_owner"] == "Operations Lead"
    assert payload["readiness_score"] == report.workflow_readiness_score
    assert payload["readiness_grade"] == report.workflow_readiness_grade
    assert [pillar["pillar"] for pillar in payload["pillars"]] == [
        pillar.value for pillar in WorkflowReadinessPillar
    ]
    assert all(
        list(pillar) == ["pillar", "score", "grade", "rationale"] for pillar in payload["pillars"]
    )
    assert payload["top_trust_gaps"] == ["First trust gap", "Second trust gap"]
    assert payload["remediation_actions"] == [
        {"id": "remediation-01", "ordinal": 1, "action": "First action"},
        {"id": "remediation-02", "ordinal": 2, "action": "Second action"},
    ]
    assert payload["source_assessment_generated_at"] == "2026-08-13T12:30:00Z"
    assert payload["diagnostic_only"] is True
    assert payload["no_decision_authority"] is True
    serialized = str(payload)
    assert "EXCLUDED_SOURCE_FINDING" not in serialized
    assert "EXCLUDED_EXECUTIVE_SUMMARY" not in serialized
    assert "EXCLUDED_UNRELATED_ACTION" not in serialized


def test_operator_summary_omits_absent_owner_and_refs() -> None:
    from scalescore.core.operator_summary import build_operator_summary

    report = _workflow_report(owner="").model_copy(
        update={"workflow_ref": None, "assessment_ref": None}
    )

    payload = build_operator_summary(report).model_dump(mode="json", exclude_none=True)

    assert "accountable_owner" not in payload
    assert "workflow_ref" not in payload
    assert "assessment_ref" not in payload


@pytest.mark.parametrize(
    (("field", "value")),
    [
        ("workflow_id", "wf-conflicting"),
        ("organization_id", "tenant-conflicting"),
    ],
)
def test_operator_summary_rejects_misaligned_workflow_reference(
    field: str,
    value: str,
) -> None:
    from scalescore.core.operator_summary import build_operator_summary

    report = _workflow_report(with_refs=True)
    assert report.workflow_ref is not None
    conflicting_ref = report.workflow_ref.model_copy(
        update={"ref": report.workflow_ref.ref.model_copy(update={field: value})}
    )

    with pytest.raises(ScaleScoreError) as exc_info:
        build_operator_summary(report.model_copy(update={"workflow_ref": conflicting_ref}))

    assert exc_info.value.code == ErrorCode.ASSESSMENT_INVALID_STATE
    assert exc_info.value.message == "Assessment is not a complete workflow diagnostic"
    assert value not in exc_info.value.message


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("assessment", "assessment_id", "assessment-conflicting"),
        ("assessment", "organization_id", "tenant-conflicting"),
        ("assessment", "environment_id", "environment-conflicting"),
        ("assessment", "assessment_type", "operational_learning_suitability"),
        ("assessment", "score", 79.0),
        ("assessment", "grade", "F"),
        ("nested_workflow", "ref_id", "workflow:tenant-a:wf-conflicting"),
        ("nested_workflow", "organization_id", "tenant-conflicting"),
        ("nested_workflow", "environment_id", "environment-conflicting"),
        ("nested_workflow", "external_uri", "/api/workflows/conflicting"),
        ("nested_workflow", "snapshot_id", "snapshot-conflicting"),
        ("nested_workflow", "version", "version-conflicting"),
    ],
)
def test_operator_summary_rejects_misaligned_assessment_reference(
    target: str,
    field: str,
    value: object,
) -> None:
    from scalescore.core.operator_summary import build_operator_summary

    report = _workflow_report(with_refs=True)
    assert report.workflow_ref is not None
    assert report.assessment_ref is not None
    assessment_ref = report.assessment_ref
    if target == "assessment":
        ref_update: dict[str, object] = {field: value}
    else:
        nested_ref = assessment_ref.ref.workflow_ref
        conflicting_nested_ref = nested_ref.model_copy(
            update={"ref": nested_ref.ref.model_copy(update={field: value})}
        )
        ref_update = {"workflow_ref": conflicting_nested_ref}
    conflicting_assessment_ref = assessment_ref.model_copy(
        update={"ref": assessment_ref.ref.model_copy(update=ref_update)}
    )

    with pytest.raises(ScaleScoreError) as exc_info:
        build_operator_summary(
            report.model_copy(update={"assessment_ref": conflicting_assessment_ref})
        )

    assert exc_info.value.code == ErrorCode.ASSESSMENT_INVALID_STATE
    assert exc_info.value.message == "Assessment is not a complete workflow diagnostic"
    assert str(value) not in exc_info.value.message


@pytest.mark.parametrize(
    ("field", "items"),
    [
        ("top_trust_gaps", [""]),
        ("top_trust_gaps", ["Valid gap", " "]),
        ("prioritized_remediation_actions", [""]),
        ("prioritized_remediation_actions", ["Valid action", "\t"]),
    ],
)
def test_operator_summary_rejects_blank_diagnostic_items(
    field: str,
    items: list[str],
) -> None:
    from scalescore.core.operator_summary import build_operator_summary

    with pytest.raises(ScaleScoreError) as exc_info:
        build_operator_summary(_workflow_report().model_copy(update={field: items}))

    assert exc_info.value.code == ErrorCode.ASSESSMENT_INVALID_STATE
    assert exc_info.value.message == "Assessment is not a complete workflow diagnostic"


@pytest.mark.parametrize(
    ("report_field", "projection_field"),
    [
        ("top_trust_gaps", "top_trust_gaps"),
        ("prioritized_remediation_actions", "remediation_actions"),
    ],
)
def test_operator_summary_preserves_empty_diagnostic_lists(
    report_field: str,
    projection_field: str,
) -> None:
    from scalescore.core.operator_summary import build_operator_summary

    summary = build_operator_summary(_workflow_report().model_copy(update={report_field: []}))

    assert summary.model_dump(mode="json")[projection_field] == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 100.1])
def test_operator_summary_rejects_invalid_readiness_score(value: float) -> None:
    from scalescore.core.operator_summary import build_operator_summary

    with pytest.raises(ScaleScoreError) as exc_info:
        build_operator_summary(
            _workflow_report().model_copy(update={"workflow_readiness_score": value})
        )

    assert exc_info.value.code == ErrorCode.ASSESSMENT_INVALID_STATE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score", float("nan")),
        ("score", float("inf")),
        ("score", -0.1),
        ("score", 100.1),
        ("grade", ""),
        ("rationale", " "),
    ],
)
def test_operator_summary_rejects_incomplete_pillar_summary(
    field: str,
    value: float | str,
) -> None:
    from scalescore.core.operator_summary import build_operator_summary

    report = _workflow_report()
    first_pillar, *remaining_pillars = report.workflow_pillar_scores
    invalid_pillars = [
        first_pillar.model_copy(update={field: value}),
        *remaining_pillars,
    ]

    with pytest.raises(ScaleScoreError) as exc_info:
        build_operator_summary(
            report.model_copy(update={"workflow_pillar_scores": invalid_pillars})
        )

    assert exc_info.value.code == ErrorCode.ASSESSMENT_INVALID_STATE


@pytest.mark.parametrize(
    "report",
    [
        ScaleScoreReport(
            report_id="org-only",
            org_id="tenant-a",
            assessment_mode=AssessmentMode.ORGANIZATION,
            overall_score=80.0,
            overall_grade="B",
        ),
        _workflow_report().model_copy(update={"workflow_pillar_scores": []}),
    ],
    ids=["organization-only", "structurally-incomplete"],
)
def test_operator_summary_fails_closed_for_non_projectable_assessments(
    report: ScaleScoreReport,
) -> None:
    from scalescore.core.operator_summary import build_operator_summary

    with pytest.raises(ScaleScoreError) as exc_info:
        build_operator_summary(report)

    assert exc_info.value.code == ErrorCode.ASSESSMENT_INVALID_STATE
    assert exc_info.value.message == "Assessment is not a complete workflow diagnostic"
