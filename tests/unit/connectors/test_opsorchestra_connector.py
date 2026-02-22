from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from scalescore.connectors.opsorchestra_connector import OpsOrchestraConnector
from scalescore.core.exceptions import ErrorCode, ScaleScoreError
from scalescore.models.scaling import Recommendation, RiskIndicator, ScaleScoreReport


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


def test_is_configured_false_without_url() -> None:
    connector = OpsOrchestraConnector(outbound_url=None)
    assert connector.is_configured() is False


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
        def __init__(self, timeout: float) -> None:
            captured["timeout"] = timeout

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
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["event_type"] == "scalescore.assessment.completed"
    assert payload["tenant_id"] == "tenant_1"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer token-123"
