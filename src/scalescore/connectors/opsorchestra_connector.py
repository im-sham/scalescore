from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from scalescore.config import settings
from scalescore.core.exceptions import ErrorCode, ScaleScoreError
from scalescore.core.logging import get_logger
from scalescore.models.scaling import ScaleScoreReport

logger = get_logger(__name__)


class OpsOrchestraConnector:
    """Connector for outbound ScaleScore event delivery to OpsOrchestra."""

    def __init__(
        self,
        *,
        outbound_url: str | None = None,
        outbound_token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._outbound_url = outbound_url or settings.integration.opsorchestra_outbound_url
        self._outbound_token = (
            outbound_token
            if outbound_token is not None
            else (
                settings.integration.opsorchestra_outbound_token.get_secret_value()
                if settings.integration.opsorchestra_outbound_token
                else None
            )
        )
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.integration.opsorchestra_outbound_timeout_seconds
        )

    def is_configured(self) -> bool:
        return bool(self._outbound_url)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "scalescore/0.1",
        }
        if self._outbound_token:
            headers["Authorization"] = f"Bearer {self._outbound_token}"
        return headers

    def _event_payload(
        self,
        *,
        report: ScaleScoreReport,
        tenant_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        return {
            "event_type": "scalescore.assessment.completed",
            "occurred_at": datetime.now(UTC).isoformat(),
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "report": {
                "report_id": report.report_id,
                "org_id": report.org_id,
                "org_name": report.org_name,
                "generated_at": report.generated_at.isoformat(),
                "overall_score": report.overall_score,
                "overall_grade": report.overall_grade,
                "overall_trend": report.overall_trend,
                "total_risks": report.total_risks,
                "critical_risks": report.critical_risks,
                "high_risks": report.high_risks,
                "total_constraints": report.total_constraints,
                "total_recommendations": report.total_recommendations,
            },
            "top_risks": [
                {
                    "id": risk.id,
                    "title": risk.title,
                    "risk_level": risk.risk_level,
                    "functional_area": risk.functional_area,
                    "risk_score": risk.risk_score,
                }
                for risk in report.top_risks[:5]
            ],
            "recommendations": [
                {
                    "id": recommendation.id,
                    "title": recommendation.title,
                    "effort": recommendation.effort,
                    "impact": recommendation.impact,
                    "priority_score": recommendation.priority_score,
                }
                for recommendation in report.recommendations[:5]
            ],
        }

    async def push_assessment_report(
        self,
        *,
        report: ScaleScoreReport,
        tenant_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        if not self._outbound_url:
            raise ScaleScoreError(
                message="OpsOrchestra outbound URL is not configured",
                code=ErrorCode.CONFIGURATION_ERROR,
            )

        payload = self._event_payload(
            report=report,
            tenant_id=tenant_id,
            actor_id=actor_id,
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    self._outbound_url,
                    json=payload,
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as err:
            raise ScaleScoreError(
                message="Failed to push assessment report to OpsOrchestra",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"outbound_url": self._outbound_url},
                cause=err,
            ) from err

        logger.info(
            "opsorchestra_sync_success",
            outbound_url=self._outbound_url,
            report_id=report.report_id,
            tenant_id=tenant_id,
            status_code=response.status_code,
        )
        response_body: dict[str, Any] | str
        if "application/json" in response.headers.get("content-type", "").lower():
            response_body = response.json()
        else:
            response_body = response.text

        return {
            "status_code": response.status_code,
            "response": response_body,
        }


def get_opsorchestra_connector() -> OpsOrchestraConnector:
    return OpsOrchestraConnector()
