import hmac
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from scalescore.api.dependencies.auth import RequirePermission
from scalescore.api.exception_handlers import register_exception_handlers
from scalescore.api.middleware import CorrelationIdMiddleware, RequestLoggingMiddleware
from scalescore.api.v1.auth import router as auth_router
from scalescore.config import settings
from scalescore.connectors.csv_connector import CSVConnector
from scalescore.connectors.opsorchestra_connector import (
    OpsOrchestraConnector,
    get_opsorchestra_connector,
)
from scalescore.core.assessment import run_assessment_from_csv
from scalescore.core.audit import (
    AuditEventType,
    audit_assessment_created,
    audit_data_export,
    audit_log,
)
from scalescore.core.auth.jwt import TokenPayload
from scalescore.core.auth.roles import Permission
from scalescore.core.exceptions import AssessmentNotFoundError
from scalescore.core.logging import get_logger, setup_logging
from scalescore.core.reporting import render_report_pdf
from scalescore.models.core import (
    BaseEntity,
    EntityType,
    Facility,
    Organization,
    System,
    Team,
    Vendor,
)
from scalescore.models.scaling import (
    ScaleScoreReport,
    ScoreHistoryComparison,
    ScoreHistoryPoint,
    ScoreHistoryResponse,
    ScoreHistoryTrendWindow,
)
from scalescore.storage.assessment_repository import (
    AssessmentRepository,
    get_assessment_repository,
)
from scalescore.storage.entity_repository import (
    EntityRepository,
    get_entity_repository,
)

setup_logging()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "application_started",
        host=settings.server.host,
        port=settings.server.port,
    )
    yield
    logger.info("application_shutdown")


app = FastAPI(
    title=settings.app_name,
    description="Operational Readiness Prediction System",
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIdMiddleware)

register_exception_handlers(app)

app.include_router(auth_router, prefix="/api/v1")

ORGANIZATIONS_FILE = File(...)  # noqa: B008
TEAMS_FILE = File(...)  # noqa: B008
SYSTEMS_FILE = File(...)  # noqa: B008
VENDORS_FILE = File(...)  # noqa: B008
FACILITIES_FILE = File(...)  # noqa: B008
GROWTH_SIGNALS_FILE = File(...)  # noqa: B008


CanCreateAssessments = Annotated[
    TokenPayload, Depends(RequirePermission(Permission.ASSESSMENT_CREATE))
]
CanReadAssessments = Annotated[
    TokenPayload, Depends(RequirePermission(Permission.ASSESSMENT_READ))
]
CanExportReports = Annotated[
    TokenPayload, Depends(RequirePermission(Permission.REPORT_EXPORT))
]
CanManageOrganizations = Annotated[
    TokenPayload, Depends(RequirePermission(Permission.ORGANIZATION_MANAGE))
]
AssessmentRepositoryDep = Annotated[AssessmentRepository, Depends(get_assessment_repository)]
EntityRepositoryDep = Annotated[EntityRepository, Depends(get_entity_repository)]
OpsOrchestraConnectorDep = Annotated[OpsOrchestraConnector, Depends(get_opsorchestra_connector)]

EntityResponse = Organization | Team | System | Vendor | Facility | BaseEntity

ENTITY_MODEL_BY_TYPE: dict[EntityType, type[BaseEntity]] = {
    EntityType.ORGANIZATION: Organization,
    EntityType.TEAM: Team,
    EntityType.SYSTEM: System,
    EntityType.VENDOR: Vendor,
    EntityType.FACILITY: Facility,
}
ENTITY_TYPE_ALIASES: dict[str, EntityType] = {
    "organization": EntityType.ORGANIZATION,
    "organizations": EntityType.ORGANIZATION,
    "team": EntityType.TEAM,
    "teams": EntityType.TEAM,
    "system": EntityType.SYSTEM,
    "systems": EntityType.SYSTEM,
    "vendor": EntityType.VENDOR,
    "vendors": EntityType.VENDOR,
    "facility": EntityType.FACILITY,
    "facilities": EntityType.FACILITY,
    "role": EntityType.ROLE,
    "roles": EntityType.ROLE,
    "process": EntityType.PROCESS,
    "processes": EntityType.PROCESS,
}


class OpsOrchestraWebhookEvent(BaseModel):
    event_type: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    event_id: str | None = None
    occurred_at: datetime | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    entity: dict[str, Any] | None = None


def _dataset_path_for_development(dataset_path: str) -> Path:
    if not settings.is_development():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "DATASET_PATH_DISABLED",
                "message": "dataset_path assessments are only available in development mode",
            },
        )

    resolved = Path(dataset_path).resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_DATASET_PATH",
                "message": "dataset_path must point to an existing directory",
            },
        )
    return resolved


def _validate_opsorchestra_webhook_secret(provided_secret: str | None) -> None:
    configured_secret = settings.integration.opsorchestra_webhook_secret
    if configured_secret is None:
        if settings.is_production():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "WEBHOOK_SECRET_NOT_CONFIGURED",
                    "message": "Webhook secret must be configured in production",
                },
            )
        return

    expected = configured_secret.get_secret_value()
    if not provided_secret or not hmac.compare_digest(provided_secret, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_WEBHOOK_SECRET", "message": "Webhook secret is invalid"},
        )


def _normalize_entity_type(entity_type: str, *, allow_organizations: bool = True) -> EntityType:
    normalized = entity_type.strip().lower()
    parsed = ENTITY_TYPE_ALIASES.get(normalized)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_ENTITY_TYPE",
                "message": f"Unsupported entity_type: {entity_type}",
            },
        )
    if not allow_organizations and parsed == EntityType.ORGANIZATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_ENTITY_TYPE",
                "message": "Use /api/v1/organizations for organization records",
            },
        )
    return parsed


def _entity_model_for_type(entity_type: EntityType) -> type[BaseEntity]:
    return ENTITY_MODEL_BY_TYPE.get(entity_type, BaseEntity)


def _coerce_entity_payload(entity_type: EntityType, payload: dict[str, Any]) -> BaseEntity:
    model_cls = _entity_model_for_type(entity_type)
    try:
        entity = model_cls.model_validate(payload)
    except Exception as err:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_ENTITY_PAYLOAD",
                "message": str(err),
            },
        ) from err

    if entity.type != entity_type:
        entity = entity.model_copy(update={"type": entity_type})

    if entity_type != EntityType.ORGANIZATION and hasattr(entity, "org_id"):
        org_id = getattr(entity, "org_id", None)
        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "ORG_ID_REQUIRED",
                    "message": "org_id is required for non-organization entities",
                },
            )

    return entity


def _score_delta_within_window(
    points: list[ScoreHistoryPoint],
    *,
    now: datetime,
    days: int,
) -> ScoreHistoryTrendWindow:
    if not points:
        return ScoreHistoryTrendWindow(days=days)

    current = points[0].overall_score
    cutoff = now - timedelta(days=days)
    comparison = next((point for point in points if point.generated_at <= cutoff), None)
    if comparison is None:
        return ScoreHistoryTrendWindow(days=days)

    delta = round(current - comparison.overall_score, 2)
    direction = "stable"
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    return ScoreHistoryTrendWindow(
        days=days,
        delta=delta,
        direction=direction,
        compared_report_id=comparison.report_id,
    )


def _history_comparison(points: list[ScoreHistoryPoint]) -> ScoreHistoryComparison:
    if len(points) < 2:
        return ScoreHistoryComparison()

    current = points[0]
    previous = points[1]
    score_delta = round(current.overall_score - previous.overall_score, 2)

    return ScoreHistoryComparison(
        current_report_id=current.report_id,
        previous_report_id=previous.report_id,
        score_delta=score_delta,
        risk_delta=current.total_risks - previous.total_risks,
        critical_risk_delta=current.critical_risks - previous.critical_risks,
        generated_at_delta_hours=round(
            (current.generated_at - previous.generated_at).total_seconds() / 3600, 2
        ),
    )


def _csv_loader_for_entity_type(entity_type: EntityType) -> Callable[[str | Path], list[Any]]:
    connector = CSVConnector()
    loaders: dict[EntityType, Callable[[str | Path], list[Any]]] = {
        EntityType.ORGANIZATION: connector.load_organizations,
        EntityType.TEAM: connector.load_teams,
        EntityType.SYSTEM: connector.load_systems,
        EntityType.VENDOR: connector.load_vendors,
        EntityType.FACILITY: connector.load_facilities,
    }
    loader = loaders.get(entity_type)
    if loader is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_ENTITY_TYPE",
                "message": f"CSV import unsupported for entity_type: {entity_type.value}",
            },
        )
    return loader


@app.post("/api/v1/assessments", response_model=ScaleScoreReport)
async def create_assessment(
    dataset_path: str,
    current_user: CanCreateAssessments,
    repository: AssessmentRepositoryDep,
) -> ScaleScoreReport:
    report = run_assessment_from_csv(_dataset_path_for_development(dataset_path))
    repository.save_report(report, tenant_id=current_user.tenant_id)
    audit_assessment_created(
        user_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        assessment_id=report.report_id,
        organization_id=report.org_id,
    )
    return report


@app.post("/api/v1/assessments/upload", response_model=ScaleScoreReport)
async def create_assessment_from_upload(
    current_user: CanCreateAssessments,
    repository: AssessmentRepositoryDep,
    organizations: UploadFile = ORGANIZATIONS_FILE,  # noqa: B008
    teams: UploadFile = TEAMS_FILE,  # noqa: B008
    systems: UploadFile = SYSTEMS_FILE,  # noqa: B008
    vendors: UploadFile = VENDORS_FILE,  # noqa: B008
    facilities: UploadFile = FACILITIES_FILE,  # noqa: B008
    growth_signals: UploadFile = GROWTH_SIGNALS_FILE,  # noqa: B008
) -> ScaleScoreReport:
    files = {
        "organizations.csv": organizations,
        "teams.csv": teams,
        "systems.csv": systems,
        "vendors.csv": vendors,
        "facilities.csv": facilities,
        "growth_signals.csv": growth_signals,
    }

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        for filename, upload in files.items():
            content = await upload.read()
            (temp_path / filename).write_bytes(content)
        report = run_assessment_from_csv(temp_path)

    repository.save_report(report, tenant_id=current_user.tenant_id)
    audit_assessment_created(
        user_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        assessment_id=report.report_id,
        organization_id=report.org_id,
    )
    return report


@app.get("/api/v1/assessments/{assessment_id}", response_model=ScaleScoreReport)
async def get_assessment(
    assessment_id: str,
    current_user: CanReadAssessments,
    repository: AssessmentRepositoryDep,
) -> ScaleScoreReport:
    report = repository.get_report(assessment_id, tenant_id=current_user.tenant_id)
    if report is None:
        raise AssessmentNotFoundError(assessment_id)

    audit_log(
        AuditEventType.ASSESSMENT_VIEWED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="assessment",
        resource_id=assessment_id,
    )
    return report


@app.get("/api/v1/assessments/{assessment_id}/export/pdf")
async def export_assessment_pdf(
    assessment_id: str,
    current_user: CanExportReports,
    repository: AssessmentRepositoryDep,
) -> Response:
    report = repository.get_report(assessment_id, tenant_id=current_user.tenant_id)
    if report is None:
        raise AssessmentNotFoundError(assessment_id)

    pdf_content = render_report_pdf(report)
    audit_log(
        AuditEventType.REPORT_EXPORTED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="assessment_pdf",
        resource_id=assessment_id,
    )
    audit_data_export(
        user_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        export_type="assessment_pdf",
        record_count=1,
    )
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="scalescore-assessment-{assessment_id}.pdf"'
            )
        },
    )


@app.post("/api/v1/assessments/{assessment_id}/sync/opsorchestra")
async def sync_assessment_to_opsorchestra(
    assessment_id: str,
    current_user: CanExportReports,
    repository: AssessmentRepositoryDep,
    connector: OpsOrchestraConnectorDep,
) -> dict[str, Any]:
    report = repository.get_report(assessment_id, tenant_id=current_user.tenant_id)
    if report is None:
        raise AssessmentNotFoundError(assessment_id)

    if not connector.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "OPSORCHESTRA_SYNC_NOT_CONFIGURED",
                "message": "OpsOrchestra outbound sync URL is not configured",
            },
        )

    sync_result = await connector.push_assessment_report(
        report=report,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.sub,
    )
    audit_data_export(
        user_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        export_type="opsorchestra_sync",
        record_count=1,
    )
    audit_log(
        AuditEventType.DATA_EXPORTED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="opsorchestra_sync",
        resource_id=assessment_id,
        details={"status_code": sync_result["status_code"]},
    )
    return {
        "status": "synced",
        "assessment_id": assessment_id,
        "tenant_id": current_user.tenant_id,
        "opsorchestra": sync_result,
    }


@app.get("/api/v1/assessments", response_model=list[ScaleScoreReport])
async def list_assessments(
    current_user: CanReadAssessments,
    repository: AssessmentRepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ScaleScoreReport]:
    reports = repository.list_reports(
        tenant_id=current_user.tenant_id,
        limit=limit,
        offset=offset,
    )
    audit_log(
        AuditEventType.ASSESSMENT_VIEWED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="assessment_list",
    )
    return reports


@app.post("/api/v1/organizations", response_model=Organization)
async def create_organization(
    payload: Organization,
    current_user: CanManageOrganizations,
    repository: EntityRepositoryDep,
) -> Organization:
    organization = payload.model_copy(update={"type": EntityType.ORGANIZATION})
    saved = repository.upsert_entity(organization, tenant_id=current_user.tenant_id)
    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="organization",
        resource_id=saved.id,
    )
    return Organization.model_validate(saved.model_dump())


@app.get("/api/v1/organizations", response_model=list[Organization])
async def list_organizations(
    current_user: CanReadAssessments,
    repository: EntityRepositoryDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Organization]:
    entities = repository.list_entities(
        current_user.tenant_id,
        entity_type=EntityType.ORGANIZATION.value,
        limit=limit,
        offset=offset,
    )
    return [Organization.model_validate(entity.model_dump()) for entity in entities]


@app.get("/api/v1/organizations/{org_id}", response_model=Organization)
async def get_organization(
    org_id: str,
    current_user: CanReadAssessments,
    repository: EntityRepositoryDep,
) -> Organization:
    organization = repository.get_entity(
        org_id,
        tenant_id=current_user.tenant_id,
        entity_type=EntityType.ORGANIZATION.value,
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORGANIZATION_NOT_FOUND", "message": "Organization not found"},
        )
    return Organization.model_validate(organization.model_dump())


@app.put("/api/v1/organizations/{org_id}", response_model=Organization)
async def update_organization(
    org_id: str,
    payload: Organization,
    current_user: CanManageOrganizations,
    repository: EntityRepositoryDep,
) -> Organization:
    if payload.id != org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "ORG_ID_MISMATCH", "message": "Path org_id must match payload id"},
        )
    organization = payload.model_copy(update={"type": EntityType.ORGANIZATION, "id": org_id})
    saved = repository.upsert_entity(organization, tenant_id=current_user.tenant_id)
    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="organization",
        resource_id=org_id,
    )
    return Organization.model_validate(saved.model_dump())


@app.delete("/api/v1/organizations/{org_id}")
async def delete_organization(
    org_id: str,
    current_user: CanManageOrganizations,
    repository: EntityRepositoryDep,
) -> dict[str, str]:
    deleted = repository.delete_entity(
        org_id,
        tenant_id=current_user.tenant_id,
        entity_type=EntityType.ORGANIZATION.value,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORGANIZATION_NOT_FOUND", "message": "Organization not found"},
        )
    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="organization",
        resource_id=org_id,
    )
    return {"message": "Organization deleted"}


@app.post("/api/v1/entities/{entity_type}", response_model=EntityResponse)
async def create_entity(
    entity_type: str,
    payload: dict[str, Any],
    current_user: CanManageOrganizations,
    repository: EntityRepositoryDep,
) -> EntityResponse:
    parsed_type = _normalize_entity_type(entity_type, allow_organizations=False)
    entity = _coerce_entity_payload(parsed_type, payload)
    saved = repository.upsert_entity(entity, tenant_id=current_user.tenant_id)
    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type=parsed_type.value,
        resource_id=saved.id,
    )
    return saved


@app.get("/api/v1/entities/{entity_type}", response_model=list[EntityResponse])
async def list_entities(
    entity_type: str,
    current_user: CanReadAssessments,
    repository: EntityRepositoryDep,
    org_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[EntityResponse]:
    parsed_type = _normalize_entity_type(entity_type, allow_organizations=False)
    return repository.list_entities(
        current_user.tenant_id,
        entity_type=parsed_type.value,
        org_id=org_id,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/entities/{entity_type}/{entity_id}", response_model=EntityResponse)
async def get_entity(
    entity_type: str,
    entity_id: str,
    current_user: CanReadAssessments,
    repository: EntityRepositoryDep,
) -> EntityResponse:
    parsed_type = _normalize_entity_type(entity_type, allow_organizations=False)
    entity = repository.get_entity(
        entity_id,
        tenant_id=current_user.tenant_id,
        entity_type=parsed_type.value,
    )
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ENTITY_NOT_FOUND", "message": "Entity not found"},
        )
    return entity


@app.put("/api/v1/entities/{entity_type}/{entity_id}", response_model=EntityResponse)
async def update_entity(
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    current_user: CanManageOrganizations,
    repository: EntityRepositoryDep,
) -> EntityResponse:
    parsed_type = _normalize_entity_type(entity_type, allow_organizations=False)
    payload["id"] = entity_id
    entity = _coerce_entity_payload(parsed_type, payload)
    saved = repository.upsert_entity(entity, tenant_id=current_user.tenant_id)
    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type=parsed_type.value,
        resource_id=entity_id,
    )
    return saved


@app.delete("/api/v1/entities/{entity_type}/{entity_id}")
async def delete_entity(
    entity_type: str,
    entity_id: str,
    current_user: CanManageOrganizations,
    repository: EntityRepositoryDep,
) -> dict[str, str]:
    parsed_type = _normalize_entity_type(entity_type, allow_organizations=False)
    deleted = repository.delete_entity(
        entity_id,
        tenant_id=current_user.tenant_id,
        entity_type=parsed_type.value,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ENTITY_NOT_FOUND", "message": "Entity not found"},
        )
    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type=parsed_type.value,
        resource_id=entity_id,
    )
    return {"message": "Entity deleted"}


@app.get("/api/v1/scores/{org_id}/history", response_model=ScoreHistoryResponse)
async def get_score_history(
    org_id: str,
    current_user: CanReadAssessments,
    repository: AssessmentRepositoryDep,
    limit: int = Query(default=20, ge=1, le=365),
) -> ScoreHistoryResponse:
    reports = repository.list_history(
        tenant_id=current_user.tenant_id,
        org_id=org_id,
        limit=limit,
    )
    points = [
        ScoreHistoryPoint(
            report_id=report.report_id,
            generated_at=report.generated_at,
            overall_score=report.overall_score,
            overall_grade=report.overall_grade,
            overall_trend=report.overall_trend,
            total_risks=report.total_risks,
            critical_risks=report.critical_risks,
            high_risks=report.high_risks,
        )
        for report in reports
    ]
    trend_7d = _score_delta_within_window(points, now=datetime.now(UTC), days=7)
    trend_30d = _score_delta_within_window(points, now=datetime.now(UTC), days=30)
    trend_90d = _score_delta_within_window(points, now=datetime.now(UTC), days=90)
    comparison = _history_comparison(points)
    audit_log(
        AuditEventType.ASSESSMENT_VIEWED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="score_history",
        resource_id=org_id,
    )
    return ScoreHistoryResponse(
        org_id=org_id,
        points=points,
        count=len(points),
        trend_7d=trend_7d,
        trend_30d=trend_30d,
        trend_90d=trend_90d,
        comparison=comparison,
    )


@app.post("/api/v1/import/csv")
async def import_from_csv(
    file: UploadFile,
    entity_type: str,
    current_user: CanCreateAssessments,
    repository: EntityRepositoryDep,
) -> dict[str, Any]:
    parsed_type = _normalize_entity_type(entity_type)
    loader = _csv_loader_for_entity_type(parsed_type)

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / (file.filename or f"{parsed_type.value}.csv")
        temp_path.write_bytes(await file.read())
        loaded_entities = loader(temp_path)

    imported_count = 0
    imported_ids: list[str] = []
    for entity in loaded_entities:
        if isinstance(entity, BaseEntity):
            saved = repository.upsert_entity(entity, tenant_id=current_user.tenant_id)
            imported_ids.append(saved.id)
            imported_count += 1

    audit_log(
        AuditEventType.DATA_IMPORTED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type=parsed_type.value,
        details={"count": imported_count, "filename": file.filename},
    )

    return {
        "status": "imported",
        "entity_type": parsed_type.value,
        "filename": file.filename,
        "imported_count": imported_count,
        "imported_ids": imported_ids,
    }


@app.post("/api/v1/webhooks/opsorchestra")
async def opsorchestra_webhook(
    event: OpsOrchestraWebhookEvent,
    repository: EntityRepositoryDep,
    x_webhook_secret: Annotated[str | None, Header(alias="X-Webhook-Secret")] = None,
) -> dict[str, Any]:
    _validate_opsorchestra_webhook_secret(x_webhook_secret)

    event_type = event.event_type.strip().lower()
    action = "ignored"
    resource_id = event.entity_id
    parsed_type: EntityType | None = None
    if event.entity_type:
        parsed_type = _normalize_entity_type(event.entity_type)

    if event_type in {"entity.created", "entity.updated"}:
        if parsed_type is None or not event.entity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_WEBHOOK_PAYLOAD",
                    "message": "entity_type and entity payload are required for upsert events",
                },
            )
        payload = dict(event.entity)
        if "id" not in payload:
            payload["id"] = event.entity_id
        if not payload.get("id"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_WEBHOOK_PAYLOAD",
                    "message": "entity_id is required for upsert events",
                },
            )
        entity = _coerce_entity_payload(parsed_type, payload)
        saved = repository.upsert_entity(entity, tenant_id=event.tenant_id)
        action = "upserted"
        resource_id = saved.id

    elif event_type == "entity.deleted":
        if parsed_type is None or not event.entity_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_WEBHOOK_PAYLOAD",
                    "message": "entity_type and entity_id are required for delete events",
                },
            )
        deleted = repository.delete_entity(
            event.entity_id,
            tenant_id=event.tenant_id,
            entity_type=parsed_type.value,
        )
        action = "deleted" if deleted else "not_found"

    audit_log(
        AuditEventType.DATA_IMPORTED,
        actor_id="opsorchestra-webhook",
        tenant_id=event.tenant_id,
        resource_type=f"webhook:{event_type}",
        resource_id=resource_id,
        details={
            "event_id": event.event_id,
            "event_type": event_type,
            "action": action,
            "entity_type": parsed_type.value if parsed_type else None,
        },
    )

    return {
        "status": "processed",
        "event_type": event_type,
        "action": action,
        "entity_type": parsed_type.value if parsed_type else None,
        "entity_id": resource_id,
    }


@app.get("/api/v1/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
    }
