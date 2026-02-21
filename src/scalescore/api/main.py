from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status

from scalescore.api.dependencies.auth import RequirePermission
from scalescore.api.exception_handlers import register_exception_handlers
from scalescore.api.middleware import CorrelationIdMiddleware, RequestLoggingMiddleware
from scalescore.api.v1.auth import router as auth_router
from scalescore.config import settings
from scalescore.core.assessment import run_assessment_from_csv
from scalescore.core.audit import AuditEventType, audit_assessment_created, audit_log
from scalescore.core.auth.jwt import TokenPayload
from scalescore.core.auth.roles import Permission
from scalescore.core.exceptions import AssessmentNotFoundError
from scalescore.core.logging import get_logger, setup_logging
from scalescore.models.scaling import ScaleScoreReport, ScoreHistoryPoint, ScoreHistoryResponse
from scalescore.storage.assessment_repository import (
    AssessmentRepository,
    get_assessment_repository,
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
AssessmentRepositoryDep = Annotated[AssessmentRepository, Depends(get_assessment_repository)]


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
    audit_log(
        AuditEventType.ASSESSMENT_VIEWED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="score_history",
        resource_id=org_id,
    )
    return ScoreHistoryResponse(org_id=org_id, points=points, count=len(points))


@app.post("/api/v1/import/csv")
async def import_from_csv(
    file: UploadFile,
    entity_type: str,
    _: CanCreateAssessments,
) -> dict[str, Any]:
    return {
        "status": "not_implemented",
        "detail": "CSV upload endpoint is pending; use dataset_path for now.",
        "entity_type": entity_type,
        "filename": file.filename,
    }


@app.get("/api/v1/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
    }
