from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from scalescore.config import settings
from scalescore.core.exceptions import ErrorCode, ScaleScoreError
from scalescore.core.logging import get_logger
from scalescore.models.core import (
    BaseEntity,
    EntityType,
    Facility,
    Organization,
    System,
    Team,
    Vendor,
)
from scalescore.models.scaling import ScaleScoreReport

logger = get_logger(__name__)


class OpsOrchestraConnector:
    """Connector for outbound ScaleScore event delivery to OpsOrchestra."""

    def __init__(
        self,
        *,
        graph_export_url: str | None = None,
        graph_token: str | None = None,
        graph_timeout_seconds: float | None = None,
        outbound_url: str | None = None,
        outbound_token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._graph_export_url = graph_export_url or settings.integration.opsorchestra_graph_export_url
        self._graph_token = (
            graph_token
            if graph_token is not None
            else (
                settings.integration.opsorchestra_graph_token.get_secret_value()
                if settings.integration.opsorchestra_graph_token
                else None
            )
        )
        self._graph_timeout_seconds = (
            graph_timeout_seconds
            if graph_timeout_seconds is not None
            else settings.integration.opsorchestra_graph_timeout_seconds
        )
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

    def is_graph_pull_configured(self) -> bool:
        return bool(self._graph_export_url)

    def is_configured(self) -> bool:
        return bool(self._outbound_url)

    def _graph_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "scalescore/0.1",
        }
        if self._graph_token:
            headers["Authorization"] = f"Bearer {self._graph_token}"
        return headers

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "scalescore/0.1",
        }
        if self._outbound_token:
            headers["Authorization"] = f"Bearer {self._outbound_token}"
        return headers

    @staticmethod
    def _coerce_graph_entity_payload(
        raw_payload: dict[str, Any],
        *,
        entity_type: EntityType,
    ) -> dict[str, Any]:
        payload = dict(raw_payload)
        payload.setdefault("type", entity_type.value)
        if not payload.get("name"):
            payload["name"] = payload.get("id", entity_type.value)
        return payload

    @staticmethod
    def _parse_graph_entities(
        raw_entities: Any,
        *,
        entity_type: EntityType,
        model_cls: type[BaseEntity],
    ) -> list[BaseEntity]:
        if raw_entities is None:
            return []
        if not isinstance(raw_entities, list):
            raise ScaleScoreError(
                message=f"Invalid '{entity_type.value}' payload from OpsOrchestra graph export",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            )

        parsed_entities: list[BaseEntity] = []
        for raw in raw_entities:
            if not isinstance(raw, dict):
                raise ScaleScoreError(
                    message=f"Invalid '{entity_type.value}' item from OpsOrchestra graph export",
                    code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                )
            payload = OpsOrchestraConnector._coerce_graph_entity_payload(
                raw,
                entity_type=entity_type,
            )
            try:
                entity = model_cls.model_validate(payload)
            except Exception as err:  # noqa: BLE001
                raise ScaleScoreError(
                    message=f"Failed to parse '{entity_type.value}' from OpsOrchestra graph export",
                    code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                    cause=err,
                ) from err
            if entity.type != entity_type:
                entity = entity.model_copy(update={"type": entity_type})
            parsed_entities.append(entity)

        return parsed_entities

    async def pull_entities(
        self,
        *,
        tenant_id: str,
        org_id: str | None = None,
    ) -> dict[str, list[BaseEntity]]:
        if not self._graph_export_url:
            raise ScaleScoreError(
                message="OpsOrchestra graph export URL is not configured",
                code=ErrorCode.CONFIGURATION_ERROR,
            )

        params: dict[str, str] = {"tenant_id": tenant_id}
        if org_id:
            params["org_id"] = org_id

        try:
            async with httpx.AsyncClient(timeout=self._graph_timeout_seconds) as client:
                response = await client.get(
                    self._graph_export_url,
                    params=params,
                    headers=self._graph_headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as err:
            raise ScaleScoreError(
                message="Failed to pull entities from OpsOrchestra graph export",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"graph_export_url": self._graph_export_url},
                cause=err,
            ) from err

        try:
            payload = response.json()
        except ValueError as err:
            raise ScaleScoreError(
                message="OpsOrchestra graph export response is not valid JSON",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"graph_export_url": self._graph_export_url},
                cause=err,
            ) from err

        if not isinstance(payload, dict):
            raise ScaleScoreError(
                message="OpsOrchestra graph export response must be an object",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={"graph_export_url": self._graph_export_url},
            )

        entities: dict[str, list[BaseEntity]] = {
            "organizations": self._parse_graph_entities(
                payload.get("organizations"),
                entity_type=EntityType.ORGANIZATION,
                model_cls=Organization,
            ),
            "teams": self._parse_graph_entities(
                payload.get("teams"),
                entity_type=EntityType.TEAM,
                model_cls=Team,
            ),
            "systems": self._parse_graph_entities(
                payload.get("systems"),
                entity_type=EntityType.SYSTEM,
                model_cls=System,
            ),
            "vendors": self._parse_graph_entities(
                payload.get("vendors"),
                entity_type=EntityType.VENDOR,
                model_cls=Vendor,
            ),
            "facilities": self._parse_graph_entities(
                payload.get("facilities"),
                entity_type=EntityType.FACILITY,
                model_cls=Facility,
            ),
            "roles": self._parse_graph_entities(
                payload.get("roles"),
                entity_type=EntityType.ROLE,
                model_cls=BaseEntity,
            ),
            "processes": self._parse_graph_entities(
                payload.get("processes"),
                entity_type=EntityType.PROCESS,
                model_cls=BaseEntity,
            ),
        }
        logger.info(
            "opsorchestra_graph_pull_success",
            graph_export_url=self._graph_export_url,
            tenant_id=tenant_id,
            org_id=org_id,
            organizations=len(entities["organizations"]),
            teams=len(entities["teams"]),
            systems=len(entities["systems"]),
            vendors=len(entities["vendors"]),
            facilities=len(entities["facilities"]),
            roles=len(entities["roles"]),
            processes=len(entities["processes"]),
            status_code=response.status_code,
        )
        return entities

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
