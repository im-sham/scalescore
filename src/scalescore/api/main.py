from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status

from scalescore.api.dependencies.auth import RequirePermission
from scalescore.api.exception_handlers import register_exception_handlers
from scalescore.api.middleware import CorrelationIdMiddleware, RequestLoggingMiddleware
from scalescore.api.v1.auth import router as auth_router
from scalescore.config import settings
from scalescore.connectors.csv_connector import CSVConnector
from scalescore.core.assessment import run_assessment_from_csv
from scalescore.core.audit import AuditEventType, audit_assessment_created, audit_log
from scalescore.core.auth.jwt import TokenPayload
from scalescore.core.auth.roles import Permission
from scalescore.core.exceptions import AssessmentNotFoundError
from scalescore.core.logging import get_logger, setup_logging
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
CanManageOrganizations = Annotated[
    TokenPayload, Depends(RequirePermission(Permission.ORGANIZATION_MANAGE))
]
AssessmentRepositoryDep = Annotated[AssessmentRepository, Depends(get_assessment_repository)]
EntityRepositoryDep = Annotated[EntityRepository, Depends(get_entity_repository)]

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


@app.get("/api/v1/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
    }
