from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from scalescore.config import settings
from scalescore.core.exceptions import ErrorCode, ScaleScoreError
from scalescore.core.logging import get_logger
from scalescore.core.network import validate_remote_url
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
        integration = settings.integration
        self._require_https = not (settings.is_development() or settings.is_testing())
        self._allow_private_network = integration.opsorchestra_allow_private_network

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
        self._graph_max_entities_per_type = integration.opsorchestra_graph_max_entities_per_type
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
        self._max_retries = integration.opsorchestra_http_max_retries
        self._retry_backoff_seconds = integration.opsorchestra_http_retry_backoff_seconds

        if self._graph_export_url:
            validate_remote_url(
                self._graph_export_url,
                setting_name="INTEGRATION_OPSORCHESTRA_GRAPH_EXPORT_URL",
                require_https=self._require_https,
                allow_private_network=self._allow_private_network,
            )
        if self._outbound_url:
            validate_remote_url(
                self._outbound_url,
                setting_name="INTEGRATION_OPSORCHESTRA_OUTBOUND_URL",
                require_https=self._require_https,
                allow_private_network=self._allow_private_network,
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

    def _parse_graph_entities(
        self,
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
        if len(raw_entities) > self._graph_max_entities_per_type:
            raise ScaleScoreError(
                message=f"'{entity_type.value}' payload exceeds configured per-type limit",
                code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                details={
                    "entity_type": entity_type.value,
                    "limit": self._graph_max_entities_per_type,
                    "received": len(raw_entities),
                },
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

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    async def _request_with_retry(
        self,
        *,
        operation: str,
        send: Callable[[], Awaitable[httpx.Response]],
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await send()
                if (
                    self._is_retryable_status(response.status_code)
                    and attempt < self._max_retries
                ):
                    backoff_seconds = self._retry_backoff_seconds * (2**attempt)
                    logger.warning(
                        "opsorchestra_retryable_response",
                        operation=operation,
                        status_code=response.status_code,
                        attempt=attempt + 1,
                        max_attempts=self._max_retries + 1,
                        backoff_seconds=round(backoff_seconds, 3),
                    )
                    await asyncio.sleep(backoff_seconds)
                    continue
                response.raise_for_status()
                return response
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ) as err:
                last_error = err
                if attempt >= self._max_retries:
                    break
                backoff_seconds = self._retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "opsorchestra_retryable_transport_error",
                    operation=operation,
                    attempt=attempt + 1,
                    max_attempts=self._max_retries + 1,
                    backoff_seconds=round(backoff_seconds, 3),
                    error_type=type(err).__name__,
                )
                await asyncio.sleep(backoff_seconds)
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry loop exited without response or error")

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
            async with httpx.AsyncClient(
                timeout=self._graph_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await self._request_with_retry(
                    operation="graph_pull",
                    send=lambda: client.get(
                        self._graph_export_url,
                        params=params,
                        headers=self._graph_headers(),
                    ),
                )
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
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await self._request_with_retry(
                    operation="outbound_sync",
                    send=lambda: client.post(
                        self._outbound_url,
                        json=payload,
                        headers=self._headers(),
                    ),
                )
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
