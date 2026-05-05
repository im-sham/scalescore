from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from scalescore.config import settings
from scalescore.connectors.opsorchestra_connector import OpsOrchestraConnector
from scalescore.core.assessment import apply_assessment_ref
from scalescore.core.exceptions import ErrorCode, ScaleScoreError
from scalescore.models.core import Team
from scalescore.models.scaling import (
    ClaimsSuitabilityStatus,
    ClaimsSuitabilitySummary,
    OperationalLearningAssessmentResult,
    OperationalLearningCompletenessState,
    OperationalLearningGovernanceDependencyState,
    OperationalLearningGovernanceStateStatus,
    OperationalLearningSuitabilityStatus,
    OperationalLearningSuitabilitySummary,
    Recommendation,
    RiskIndicator,
    ScaleScoreReport,
    WorkflowAssessmentContext,
    WorkflowBlastRadius,
)


def _sample_report() -> ScaleScoreReport:
    return ScaleScoreReport(
        report_id="report_1",
        org_id="org_1",
        org_name="Acme",
        generated_at=datetime(2026, 2, 22, tzinfo=UTC),
        overall_score=74.5,
        overall_grade="C",
        overall_trend="stable",
        top_risks=[
            RiskIndicator(
                id="risk_1",
                org_id="org_1",
                title="Critical CRM capacity risk",
                description="CRM is near saturation",
                risk_level="high",
                functional_area="operations",
                constraint_type="capacity",
                risk_score=0.82,
            )
        ],
        recommendations=[
            Recommendation(
                id="rec_1",
                org_id="org_1",
                title="Scale CRM throughput",
                description="Increase CRM limits and redundancy",
                recommendation_type="expand_capacity",
                target_entity_id="sys_crm",
                target_entity_type="system",
                effort="medium",
                impact="high",
                priority_score=0.91,
            )
        ],
        total_risks=4,
        critical_risks=1,
        high_risks=2,
        total_constraints=6,
        total_recommendations=3,
    )


def _claims_workflow_report() -> ScaleScoreReport:
    report = _sample_report().model_copy(
        update={
            "workflow_context": WorkflowAssessmentContext(
                workflow_id="document_ops_regulated_review_v0",
                name="Claims and Benefits Packet Review",
                business_function="document_operations",
                owner="Document Operations Lead",
                ai_role="Classify packets and route exception cases",
                systems_touched=["intake_queue", "review_console"],
                human_escalation_path=[
                    "Document Operations Lead",
                    "Compliance Reviewer",
                ],
                control_requirements=["evidence retention"],
                blast_radius=WorkflowBlastRadius.HIGH,
            ),
            "workflow_readiness_score": 72.0,
            "workflow_readiness_grade": "C",
            "claims_suitability": ClaimsSuitabilitySummary(
                profile_id="claims-hybrid-high-dollar-review-v0",
                status=ClaimsSuitabilityStatus.BLOCKED,
                score=0.0,
                top_blockers=["PHI boundary review is not complete."],
                top_reasons=["Claims rate-source traceability is not reviewed."],
                recommended_next_actions=["Complete PHI boundary review."],
                governance_dependency_state="blocked",
                evidence_gap_state="ready",
                phi_redaction_state="blocked",
                rate_source_traceability_state="review_required",
                downstream_consistency_state="blocked",
                savings_lifecycle_state="blocked",
            ),
        }
    )
    return apply_assessment_ref(report)


def _operational_learning_workflow_report() -> ScaleScoreReport:
    report = _sample_report().model_copy(
        update={
            "workflow_context": WorkflowAssessmentContext(
                workflow_id="document_ops_regulated_review_v0",
                name="Claims and Benefits Packet Review",
                business_function="document_operations",
                owner="Document Operations Lead",
                ai_role="Classify packets and route exception cases",
                systems_touched=["intake_queue", "review_console"],
                human_escalation_path=[
                    "Document Operations Lead",
                    "Compliance Reviewer",
                ],
                control_requirements=["evidence retention"],
                blast_radius=WorkflowBlastRadius.HIGH,
            ),
            "workflow_readiness_score": 78.0,
            "workflow_readiness_grade": "C",
            "key_findings": [
                "Runbook readiness is summary-only.",
                "raw_payload: SHOULD_NOT_LEAK",
            ],
            "operational_learning_suitability": OperationalLearningSuitabilitySummary(
                status=OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE,
                eval_suitability=OperationalLearningAssessmentResult(
                    score=82.0,
                    status=OperationalLearningSuitabilityStatus.EVAL_SUITABLE,
                    threshold=75.0,
                    threshold_met=True,
                ),
                internal_training_candidacy=OperationalLearningAssessmentResult(
                    score=81.0,
                    status=OperationalLearningSuitabilityStatus.TRAINING_CANDIDATE,
                    threshold=80.0,
                    threshold_met=True,
                ),
                top_blockers=[],
                top_reasons=["Review density and SOP references are strong."],
                recommended_next_actions=["Keep Governance dependency review current."],
                governance_dependency_state=OperationalLearningGovernanceDependencyState(
                    rights_completeness=OperationalLearningCompletenessState.COMPLETE,
                    provenance_completeness=OperationalLearningCompletenessState.COMPLETE,
                    redaction_readiness=OperationalLearningCompletenessState.COMPLETE,
                    residual_risk_band="low",
                    status=OperationalLearningGovernanceStateStatus.READY,
                    summary="Governance dependency summary is ready.",
                ),
            ),
        }
    )
    return apply_assessment_ref(report)


def test_is_configured_false_without_url() -> None:
    connector = OpsOrchestraConnector(outbound_url=None)
    assert connector.is_configured() is False


def test_graph_pull_is_not_configured_without_url() -> None:
    connector = OpsOrchestraConnector(graph_export_url=None)
    assert connector.is_graph_pull_configured() is False


def test_event_payload_includes_workflow_assessment_and_claims_suitability_summary() -> None:
    connector = OpsOrchestraConnector(outbound_url="https://opsorchestra.example/sync")

    payload = connector._event_payload(
        report=_claims_workflow_report(),
        tenant_id="tenant_1",
        actor_id="user_1",
    )

    report_payload = payload["report"]
    assert report_payload["assessment_id"] == "report_1"
    assert report_payload["assessment_ref_id"] == "assessment:org_1:report_1"
    assert report_payload["workflow_id"] == "document_ops_regulated_review_v0"
    assert report_payload["workflow_readiness"]["score"] == 72.0
    assert report_payload["workflow_readiness"]["grade"] == "C"
    assert report_payload["claims_suitability"] == {
        "profile_id": "claims-hybrid-high-dollar-review-v0",
        "status": "blocked",
        "score": 0.0,
        "top_blockers": ["PHI boundary review is not complete."],
        "top_reasons": ["Claims rate-source traceability is not reviewed."],
        "recommended_next_actions": ["Complete PHI boundary review."],
        "governance_dependency_state": "blocked",
        "evidence_gap_state": "ready",
        "phi_redaction_state": "blocked",
        "rate_source_traceability_state": "review_required",
        "downstream_consistency_state": "blocked",
        "savings_lifecycle_state": "blocked",
    }


def test_event_payload_includes_compact_operational_learning_suitability_summary_only() -> None:
    connector = OpsOrchestraConnector(outbound_url="https://opsorchestra.example/sync")

    payload = connector._event_payload(
        report=_operational_learning_workflow_report(),
        tenant_id="tenant_1",
        actor_id="user_1",
    )

    report_payload = payload["report"]
    assert report_payload["operational_learning_suitability"] == {
        "status": "training_candidate",
        "eval_suitability_status": "eval_suitable",
        "internal_training_candidacy_status": "training_candidate",
        "top_blockers": [],
        "top_reasons": ["Review density and SOP references are strong."],
        "recommended_next_actions": ["Keep Governance dependency review current."],
        "governance_dependency_state": {
            "status": "ready",
            "rights_completeness": "complete",
            "provenance_completeness": "complete",
            "redaction_readiness": "complete",
            "residual_risk_band": "low",
            "summary": "Governance dependency summary is ready.",
        },
    }

    serialized_payload = str(payload)
    assert "source_findings" not in serialized_payload
    assert "notes" not in serialized_payload
    assert "SHOULD_NOT_LEAK" not in serialized_payload


@pytest.mark.asyncio
async def test_pull_entities_requires_configured_graph_export_url() -> None:
    connector = OpsOrchestraConnector(graph_export_url=None)
    with pytest.raises(ScaleScoreError) as exc_info:
        await connector.pull_entities(tenant_id="tenant_1")

    assert exc_info.value.code == ErrorCode.CONFIGURATION_ERROR


@pytest.mark.asyncio
async def test_pull_entities_fetches_and_parses_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, timeout: float, follow_redirects: bool = False) -> None:
            captured["timeout"] = timeout
            captured["follow_redirects"] = follow_redirects

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        async def get(
            self,
            url: str,
            *,
            params: dict[str, str],
            headers: dict[str, str],
        ) -> httpx.Response:
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return httpx.Response(
                status_code=200,
                json={
                    "teams": [
                        {
                            "id": "team_ops",
                            "org_id": "org_1",
                            "name": "Operations",
                            "function": "operations",
                            "headcount_current": 12,
                        }
                    ]
                },
                request=httpx.Request("GET", url),
                headers={"content-type": "application/json"},
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    connector = OpsOrchestraConnector(
        graph_export_url="https://opsorchestra.example/export",
        graph_token="graph-token",
        graph_timeout_seconds=9.0,
    )

    entities = await connector.pull_entities(
        tenant_id="tenant_1",
        org_id="org_1",
    )

    assert entities["teams"]
    assert isinstance(entities["teams"][0], Team)
    assert entities["teams"][0].id == "team_ops"
    assert captured["url"] == "https://opsorchestra.example/export"
    assert captured["params"] == {"tenant_id": "tenant_1", "org_id": "org_1"}
    assert captured["timeout"] == 9.0
    assert captured["follow_redirects"] is False
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer graph-token"


@pytest.mark.asyncio
async def test_pull_entities_retries_on_retryable_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.integration, "opsorchestra_http_max_retries", 1)
    monkeypatch.setattr(settings.integration, "opsorchestra_http_retry_backoff_seconds", 0.0)
    attempts = {"count": 0}

    class FakeAsyncClient:
        def __init__(self, timeout: float, follow_redirects: bool = False) -> None:
            self._timeout = timeout

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        async def get(
            self,
            url: str,
            *,
            params: dict[str, str],
            headers: dict[str, str],
        ) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(
                    status_code=503,
                    request=httpx.Request("GET", url),
                    headers={"content-type": "application/json"},
                    json={"error": "temporary"},
                )
            return httpx.Response(
                status_code=200,
                json={"teams": []},
                request=httpx.Request("GET", url),
                headers={"content-type": "application/json"},
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    connector = OpsOrchestraConnector(
        graph_export_url="https://opsorchestra.example/export",
        graph_timeout_seconds=1.0,
    )
    entities = await connector.pull_entities(tenant_id="tenant_1")
    assert attempts["count"] == 2
    assert entities["teams"] == []


@pytest.mark.asyncio
async def test_push_assessment_report_requires_configured_url() -> None:
    connector = OpsOrchestraConnector(outbound_url=None)
    with pytest.raises(ScaleScoreError) as exc_info:
        await connector.push_assessment_report(
            report=_sample_report(),
            tenant_id="tenant_1",
            actor_id="user_1",
        )

    assert exc_info.value.code == ErrorCode.CONFIGURATION_ERROR


@pytest.mark.asyncio
async def test_push_assessment_report_posts_event_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, timeout: float, follow_redirects: bool = False) -> None:
            captured["timeout"] = timeout
            captured["follow_redirects"] = follow_redirects

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return httpx.Response(
                status_code=202,
                json={"accepted": True},
                request=httpx.Request("POST", url),
                headers={"content-type": "application/json"},
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    connector = OpsOrchestraConnector(
        outbound_url="https://opsorchestra.example/sync",
        outbound_token="token-123",
        timeout_seconds=4.0,
    )

    result = await connector.push_assessment_report(
        report=_sample_report(),
        tenant_id="tenant_1",
        actor_id="user_1",
    )

    assert result["status_code"] == 202
    assert result["response"] == {"accepted": True}
    assert captured["url"] == "https://opsorchestra.example/sync"
    assert captured["timeout"] == 4.0
    assert captured["follow_redirects"] is False
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["event_type"] == "scalescore.assessment.completed"
    assert payload["tenant_id"] == "tenant_1"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer token-123"


def test_connector_rejects_non_https_opsorchestra_url_in_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings.integration, "opsorchestra_allow_private_network", False)

    with pytest.raises(ValueError, match="must use https"):
        OpsOrchestraConnector(graph_export_url="http://opsorchestra.example/export")
