import hmac
import shutil
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

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
from scalescore.core.assessment import run_assessment_from_csv, run_workflow_assessment
from scalescore.core.async_assessment import AsyncAssessmentWorker
from scalescore.core.async_broker import AsyncAssessmentBrokerError, get_async_assessment_broker
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
from scalescore.core.rate_limit import SlidingWindowRateLimiter, get_rate_limiter
from scalescore.core.reporting import render_report_pdf
from scalescore.core.scheduled_assessment import (
    ScheduledAssessmentDispatcher,
    async_assessment_dataset_directory,
)
from scalescore.core.sensitive_summary import summary_only_text_violations
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
    DocumentOperationsReadinessProfile,
    OperationalLearningInputs,
    ScaleScoreReport,
    ScoreHistoryComparison,
    ScoreHistoryPoint,
    ScoreHistoryResponse,
    ScoreHistoryTrendWindow,
    WorkflowAssessmentContext,
    WorkflowEvidenceInput,
    WorkflowRefEnvelope,
)
from scalescore.storage.assessment_repository import (
    AssessmentRepository,
    get_assessment_repository,
)
from scalescore.storage.async_assessment_repository import (
    AsyncAssessmentJob,
    AsyncAssessmentJobRepository,
    AsyncAssessmentStatus,
    get_async_assessment_job_repository,
)
from scalescore.storage.entity_repository import (
    EntityRepository,
    get_entity_repository,
)
from scalescore.storage.scheduled_assessment_repository import (
    ScheduledAssessment,
    ScheduledAssessmentCadence,
    ScheduledAssessmentRepository,
    ScheduledAssessmentStatus,
    get_scheduled_assessment_repository,
)

setup_logging()

logger = get_logger(__name__)


def _build_async_assessment_worker() -> AsyncAssessmentWorker:
    return AsyncAssessmentWorker(
        job_repository=get_async_assessment_job_repository(),
        assessment_repository=get_assessment_repository(),
        poll_interval_seconds=settings.async_assessment.worker_poll_interval_seconds,
    )


def _build_scheduled_assessment_dispatcher() -> ScheduledAssessmentDispatcher:
    enqueue_job = _enqueue_async_assessment_job if settings.async_assessment.mode == "broker" else None
    return ScheduledAssessmentDispatcher(
        schedule_repository=get_scheduled_assessment_repository(),
        job_repository=get_async_assessment_job_repository(),
        enqueue_job=enqueue_job,
        dispatch_interval_seconds=settings.async_assessment.scheduled_dispatch_poll_interval_seconds,
        dispatch_batch_size=settings.async_assessment.scheduled_dispatch_batch_size,
    )


async def _process_async_assessment_queue_once() -> None:
    if settings.async_assessment.mode != "poll":
        return
    # Process at most one queued job per poll request. This keeps behavior deterministic
    # across environments where long-lived background tasks may not persist between requests.
    worker = _build_async_assessment_worker()
    await worker.process_next_job()


async_assessment_runtime_worker: AsyncAssessmentWorker | None = None
scheduled_assessment_runtime_dispatcher: ScheduledAssessmentDispatcher | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global async_assessment_runtime_worker, scheduled_assessment_runtime_dispatcher
    logger.info(
        "application_started",
        host=settings.server.host,
        port=settings.server.port,
    )
    if settings.features.enable_async_assessments and settings.async_assessment.mode == "background":
        async_assessment_runtime_worker = _build_async_assessment_worker()
        await async_assessment_runtime_worker.start()
        if settings.features.enable_scheduled_assessments:
            scheduled_assessment_runtime_dispatcher = _build_scheduled_assessment_dispatcher()
            await scheduled_assessment_runtime_dispatcher.start()

    try:
        yield
    finally:
        if scheduled_assessment_runtime_dispatcher is not None:
            await scheduled_assessment_runtime_dispatcher.stop()
            scheduled_assessment_runtime_dispatcher = None
        if async_assessment_runtime_worker is not None:
            await async_assessment_runtime_worker.stop()
            async_assessment_runtime_worker = None
        logger.info("application_shutdown")


app = FastAPI(
    title=settings.app_name,
    description="Workflow-first AI operational readiness scoring API",
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
AsyncAssessmentJobRepositoryDep = Annotated[
    AsyncAssessmentJobRepository, Depends(get_async_assessment_job_repository)
]
ScheduledAssessmentRepositoryDep = Annotated[
    ScheduledAssessmentRepository, Depends(get_scheduled_assessment_repository)
]
RateLimiterDep = Annotated[SlidingWindowRateLimiter, Depends(get_rate_limiter)]
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


class AsyncAssessmentJobResponse(BaseModel):
    job_id: str
    tenant_id: str
    submitted_by: str
    workflow_context: WorkflowAssessmentContext | None = None
    status: str
    progress_stage: str
    progress_percentage: int
    progress_message: str | None = None
    report_id: str | None = None
    org_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ScheduledAssessmentResponse(BaseModel):
    schedule_id: str
    tenant_id: str
    created_by: str
    name: str
    workflow_context: WorkflowAssessmentContext | None = None
    status: str
    cadence: str
    run_hour_utc: int
    run_minute_utc: int
    run_day_of_week: int | None = None
    next_run_at: datetime
    last_run_at: datetime | None = None
    last_job_id: str | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class CreateWorkflowAssessmentRequest(BaseModel):
    dataset_path: str = Field(min_length=1)
    workflow_context: WorkflowAssessmentContext


class CreateMilaWorkflowAssessmentRequest(BaseModel):
    org_id: str = Field(min_length=1)
    org_name: str = Field(min_length=1)
    workflow_context: WorkflowAssessmentContext
    workflow_ref: WorkflowRefEnvelope | None = None
    workflow_evidence: WorkflowEvidenceInput | None = None
    operational_learning_inputs: OperationalLearningInputs | None = None
    document_operations_profile: DocumentOperationsReadinessProfile | None = None
    baseline_operational_score: float | None = Field(default=None, ge=0.0, le=100.0)
    source_system: str = Field(default="mila", min_length=1)
    source_workflow_type: str | None = None
    source_runbook_id: str | None = None
    source_playbook_id: str | None = None
    source_findings: list[str] = Field(default_factory=list)
    notes: str | None = None


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


def _parse_workflow_context_json(workflow_context_json: str | None) -> WorkflowAssessmentContext | None:
    if workflow_context_json is None:
        return None

    try:
        return WorkflowAssessmentContext.model_validate_json(workflow_context_json)
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_WORKFLOW_CONTEXT",
                "message": "workflow_context_json is not a valid WorkflowAssessmentContext payload",
                "errors": err.errors(),
            },
        ) from err


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


def _async_assessment_dataset_directory(job_id: str) -> Path:
    return async_assessment_dataset_directory(job_id)


def _scheduled_assessment_dataset_directory(schedule_id: str) -> Path:
    storage_root = Path(settings.storage.assessments_db_path).resolve().parent
    return storage_root / "scheduled_assessments" / schedule_id / "dataset"


def _async_assessment_job_response(job: AsyncAssessmentJob) -> AsyncAssessmentJobResponse:
    return AsyncAssessmentJobResponse(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        submitted_by=job.submitted_by,
        workflow_context=job.workflow_context,
        status=job.status.value,
        progress_stage=job.progress_stage,
        progress_percentage=job.progress_percentage,
        progress_message=job.progress_message,
        report_id=job.report_id,
        org_id=job.org_id,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _scheduled_assessment_response(schedule: ScheduledAssessment) -> ScheduledAssessmentResponse:
    return ScheduledAssessmentResponse(
        schedule_id=schedule.schedule_id,
        tenant_id=schedule.tenant_id,
        created_by=schedule.created_by,
        name=schedule.name,
        workflow_context=schedule.workflow_context,
        status=schedule.status.value,
        cadence=schedule.cadence.value,
        run_hour_utc=schedule.run_hour_utc,
        run_minute_utc=schedule.run_minute_utc,
        run_day_of_week=schedule.run_day_of_week,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        last_job_id=schedule.last_job_id,
        last_error=schedule.last_error,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _request_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


def _enforce_rate_limit(
    *,
    rate_limiter: SlidingWindowRateLimiter,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    decision = rate_limiter.allow(
        key,
        limit=limit,
        window_seconds=window_seconds,
    )
    if decision.allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "RATE_LIMITED",
            "message": "Rate limit exceeded, retry later",
            "retry_after_seconds": decision.retry_after_seconds,
        },
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def _enforce_async_assessment_queue_limit(
    *,
    job_repository: AsyncAssessmentJobRepository,
    tenant_id: str,
) -> None:
    outstanding_jobs = job_repository.count_jobs(
        tenant_id=tenant_id,
        statuses={AsyncAssessmentStatus.QUEUED, AsyncAssessmentStatus.PROCESSING},
    )
    queue_limit = settings.async_assessment.max_outstanding_jobs_per_tenant
    if outstanding_jobs < queue_limit:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "ASYNC_QUEUE_LIMIT_REACHED",
            "message": (
                "Outstanding async assessment queue limit reached for tenant. "
                "Retry after existing jobs complete."
            ),
            "max_outstanding_jobs_per_tenant": queue_limit,
        },
    )


def _enqueue_async_assessment_job(job_id: str) -> None:
    if settings.async_assessment.mode != "broker":
        return
    broker = get_async_assessment_broker()
    broker.enqueue(job_id)


def _parse_schedule_cadence(value: str) -> ScheduledAssessmentCadence:
    try:
        return ScheduledAssessmentCadence(value.strip().lower())
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_SCHEDULE_CADENCE",
                "message": "cadence must be one of: daily, weekly",
            },
        ) from err


def _parse_schedule_status(value: str) -> ScheduledAssessmentStatus:
    try:
        return ScheduledAssessmentStatus(value.strip().lower())
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_SCHEDULE_STATUS",
                "message": "status must be one of: active, paused",
            },
        ) from err


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


@app.post("/api/v1/assessments/workflow", response_model=ScaleScoreReport)
async def create_workflow_assessment(
    payload: CreateWorkflowAssessmentRequest,
    current_user: CanCreateAssessments,
    repository: AssessmentRepositoryDep,
) -> ScaleScoreReport:
    report = run_assessment_from_csv(
        _dataset_path_for_development(payload.dataset_path),
        workflow_context=payload.workflow_context,
    )
    repository.save_report(report, tenant_id=current_user.tenant_id)
    audit_assessment_created(
        user_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        assessment_id=report.report_id,
        organization_id=report.org_id,
    )
    return report


@app.post("/api/v1/assessments/mila/workflow", response_model=ScaleScoreReport)
async def create_mila_workflow_assessment(
    payload: CreateMilaWorkflowAssessmentRequest,
    current_user: CanCreateAssessments,
    repository: AssessmentRepositoryDep,
) -> ScaleScoreReport:
    _validate_mila_workflow_summary_text(payload)
    source_findings = list(payload.source_findings)
    if payload.source_workflow_type:
        source_findings.append(f"Workflow source type: {payload.source_workflow_type}.")
    if payload.source_runbook_id:
        source_findings.append(f"Mila runbook source: {payload.source_runbook_id}.")
    if payload.source_playbook_id:
        source_findings.append(f"Mila playbook source: {payload.source_playbook_id}.")
    if payload.notes:
        source_findings.append(payload.notes)

    report = run_workflow_assessment(
        org_id=payload.org_id,
        org_name=payload.org_name,
        workflow_context=payload.workflow_context,
        workflow_ref=payload.workflow_ref,
        baseline_operational_score=payload.baseline_operational_score,
        workflow_evidence=payload.workflow_evidence,
        operational_learning_inputs=payload.operational_learning_inputs,
        document_operations_profile=payload.document_operations_profile,
        source_findings=source_findings,
    )
    repository.save_report(report, tenant_id=current_user.tenant_id)
    audit_assessment_created(
        user_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        assessment_id=report.report_id,
        organization_id=report.org_id,
    )
    return report


def _validate_mila_workflow_summary_text(payload: CreateMilaWorkflowAssessmentRequest) -> None:
    violations = summary_only_text_violations(
        {
            "source_findings": payload.source_findings,
            "notes": payload.notes,
        }
    )
    if not violations:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "SUMMARY_ONLY_INPUT_REQUIRED",
            "message": (
                "Direct workflow assessment source_findings and notes must be compact "
                "summaries or refs, not raw payload text or sensitive field dumps."
            ),
            "fields": sorted(violations),
        },
    )


@app.post("/api/v1/assessments/upload", response_model=ScaleScoreReport)
async def create_assessment_from_upload(
    current_user: CanCreateAssessments,
    repository: AssessmentRepositoryDep,
    workflow_context_json: str | None = Form(default=None),  # noqa: B008
    organizations: UploadFile = ORGANIZATIONS_FILE,  # noqa: B008
    teams: UploadFile = TEAMS_FILE,  # noqa: B008
    systems: UploadFile = SYSTEMS_FILE,  # noqa: B008
    vendors: UploadFile = VENDORS_FILE,  # noqa: B008
    facilities: UploadFile = FACILITIES_FILE,  # noqa: B008
    growth_signals: UploadFile = GROWTH_SIGNALS_FILE,  # noqa: B008
) -> ScaleScoreReport:
    workflow_context = _parse_workflow_context_json(workflow_context_json)
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
        report = run_assessment_from_csv(temp_path, workflow_context=workflow_context)

    repository.save_report(report, tenant_id=current_user.tenant_id)
    audit_assessment_created(
        user_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        assessment_id=report.report_id,
        organization_id=report.org_id,
    )
    return report


@app.post(
    "/api/v1/assessments/async/upload",
    response_model=AsyncAssessmentJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_async_assessment_from_upload(
    request: Request,
    current_user: CanCreateAssessments,
    job_repository: AsyncAssessmentJobRepositoryDep,
    rate_limiter: RateLimiterDep,
    workflow_context_json: str | None = Form(default=None),  # noqa: B008
    organizations: UploadFile = ORGANIZATIONS_FILE,  # noqa: B008
    teams: UploadFile = TEAMS_FILE,  # noqa: B008
    systems: UploadFile = SYSTEMS_FILE,  # noqa: B008
    vendors: UploadFile = VENDORS_FILE,  # noqa: B008
    facilities: UploadFile = FACILITIES_FILE,  # noqa: B008
    growth_signals: UploadFile = GROWTH_SIGNALS_FILE,  # noqa: B008
) -> AsyncAssessmentJobResponse:
    if not settings.features.enable_async_assessments:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ASYNC_ASSESSMENTS_DISABLED",
                "message": "Async assessment processing is not enabled",
            },
        )

    _enforce_rate_limit(
        rate_limiter=rate_limiter,
        key=f"async_assessment:submit:{current_user.tenant_id}:{_request_ip(request)}",
        limit=settings.async_assessment.submit_rate_limit_requests,
        window_seconds=settings.async_assessment.submit_rate_limit_window_seconds,
    )
    _enforce_async_assessment_queue_limit(
        job_repository=job_repository,
        tenant_id=current_user.tenant_id,
    )
    workflow_context = _parse_workflow_context_json(workflow_context_json)

    files = {
        "organizations.csv": organizations,
        "teams.csv": teams,
        "systems.csv": systems,
        "vendors.csv": vendors,
        "facilities.csv": facilities,
        "growth_signals.csv": growth_signals,
    }
    job_id = f"job_{uuid4().hex[:16]}"
    dataset_directory = _async_assessment_dataset_directory(job_id)
    max_upload_bytes = settings.async_assessment.max_upload_bytes_per_file
    dataset_directory.mkdir(parents=True, exist_ok=True)
    try:
        for filename, upload in files.items():
            content = await upload.read()
            if not content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "EMPTY_UPLOAD_FILE",
                        "message": f"{filename} is empty",
                    },
                )
            if len(content) > max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "UPLOAD_FILE_TOO_LARGE",
                        "message": f"{filename} exceeds max upload size",
                        "max_upload_bytes_per_file": max_upload_bytes,
                    },
                )
            (dataset_directory / filename).write_bytes(content)

        job = job_repository.create_job(
            job_id=job_id,
            tenant_id=current_user.tenant_id,
            submitted_by=current_user.sub,
            dataset_path=str(dataset_directory),
            workflow_context=workflow_context,
        )
        try:
            _enqueue_async_assessment_job(job.job_id)
        except AsyncAssessmentBrokerError as err:
            job_repository.mark_failed(
                job_id=job.job_id,
                error_message="Failed to enqueue async assessment job for broker processing",
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "ASYNC_BROKER_UNAVAILABLE",
                    "message": (
                        "Async assessment broker unavailable. "
                        "Job was marked failed and can be retried."
                    ),
                },
            ) from err
    except Exception:
        shutil.rmtree(dataset_directory, ignore_errors=True)
        raise

    audit_log(
        AuditEventType.ASSESSMENT_CREATED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="async_assessment_job",
        resource_id=job.job_id,
    )
    return _async_assessment_job_response(job)


@app.get(
    "/api/v1/assessments/async/{job_id}",
    response_model=AsyncAssessmentJobResponse,
)
async def get_async_assessment_job(
    job_id: str,
    current_user: CanReadAssessments,
    job_repository: AsyncAssessmentJobRepositoryDep,
) -> AsyncAssessmentJobResponse:
    await _process_async_assessment_queue_once()

    job = job_repository.get_job(job_id, tenant_id=current_user.tenant_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ASYNC_ASSESSMENT_JOB_NOT_FOUND",
                "message": "Async assessment job not found",
            },
        )

    audit_log(
        AuditEventType.ASSESSMENT_VIEWED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="async_assessment_job",
        resource_id=job_id,
    )
    return _async_assessment_job_response(job)


@app.post(
    "/api/v1/assessments/schedules/upload",
    response_model=ScheduledAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_scheduled_assessment_from_upload(
    request: Request,
    current_user: CanCreateAssessments,
    schedule_repository: ScheduledAssessmentRepositoryDep,
    rate_limiter: RateLimiterDep,
    name: str = Form(..., min_length=1, max_length=200),  # noqa: B008
    cadence: str = Form(...),  # noqa: B008
    run_hour_utc: int = Form(..., ge=0, le=23),  # noqa: B008
    run_minute_utc: int = Form(..., ge=0, le=59),  # noqa: B008
    run_day_of_week: int | None = Form(default=None, ge=0, le=6),  # noqa: B008
    workflow_context_json: str | None = Form(default=None),  # noqa: B008
    organizations: UploadFile = ORGANIZATIONS_FILE,  # noqa: B008
    teams: UploadFile = TEAMS_FILE,  # noqa: B008
    systems: UploadFile = SYSTEMS_FILE,  # noqa: B008
    vendors: UploadFile = VENDORS_FILE,  # noqa: B008
    facilities: UploadFile = FACILITIES_FILE,  # noqa: B008
    growth_signals: UploadFile = GROWTH_SIGNALS_FILE,  # noqa: B008
) -> ScheduledAssessmentResponse:
    if not settings.features.enable_async_assessments:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ASYNC_ASSESSMENTS_DISABLED",
                "message": "Async assessment processing is not enabled",
            },
        )
    if not settings.features.enable_scheduled_assessments:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SCHEDULED_ASSESSMENTS_DISABLED",
                "message": "Scheduled assessments are not enabled",
            },
        )

    _enforce_rate_limit(
        rate_limiter=rate_limiter,
        key=f"scheduled_assessment:create:{current_user.tenant_id}:{_request_ip(request)}",
        limit=settings.async_assessment.submit_rate_limit_requests,
        window_seconds=settings.async_assessment.submit_rate_limit_window_seconds,
    )

    parsed_cadence = _parse_schedule_cadence(cadence)
    if parsed_cadence == ScheduledAssessmentCadence.WEEKLY and run_day_of_week is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "RUN_DAY_OF_WEEK_REQUIRED",
                "message": "run_day_of_week is required when cadence=weekly",
            },
        )

    workflow_context = _parse_workflow_context_json(workflow_context_json)
    files = {
        "organizations.csv": organizations,
        "teams.csv": teams,
        "systems.csv": systems,
        "vendors.csv": vendors,
        "facilities.csv": facilities,
        "growth_signals.csv": growth_signals,
    }
    schedule_id = f"schedule_{uuid4().hex[:16]}"
    dataset_directory = _scheduled_assessment_dataset_directory(schedule_id)
    max_upload_bytes = settings.async_assessment.max_upload_bytes_per_file
    dataset_directory.mkdir(parents=True, exist_ok=True)
    try:
        for filename, upload in files.items():
            content = await upload.read()
            if not content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "EMPTY_UPLOAD_FILE",
                        "message": f"{filename} is empty",
                    },
                )
            if len(content) > max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "UPLOAD_FILE_TOO_LARGE",
                        "message": f"{filename} exceeds max upload size",
                        "max_upload_bytes_per_file": max_upload_bytes,
                    },
                )
            (dataset_directory / filename).write_bytes(content)

        schedule = schedule_repository.create_schedule(
            schedule_id=schedule_id,
            tenant_id=current_user.tenant_id,
            created_by=current_user.sub,
            name=name,
            cadence=parsed_cadence,
            run_hour_utc=run_hour_utc,
            run_minute_utc=run_minute_utc,
            run_day_of_week=run_day_of_week if parsed_cadence == ScheduledAssessmentCadence.WEEKLY else None,
            dataset_path=str(dataset_directory),
            workflow_context=workflow_context,
        )
    except Exception:
        shutil.rmtree(dataset_directory, ignore_errors=True)
        raise

    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="scheduled_assessment",
        resource_id=schedule.schedule_id,
    )
    return _scheduled_assessment_response(schedule)


@app.get(
    "/api/v1/assessments/schedules",
    response_model=list[ScheduledAssessmentResponse],
)
async def list_scheduled_assessments(
    current_user: CanReadAssessments,
    schedule_repository: ScheduledAssessmentRepositoryDep,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ScheduledAssessmentResponse]:
    parsed_status = _parse_schedule_status(status_filter) if status_filter else None
    schedules = schedule_repository.list_schedules(
        tenant_id=current_user.tenant_id,
        status=parsed_status,
        limit=limit,
        offset=offset,
    )
    return [_scheduled_assessment_response(schedule) for schedule in schedules]


@app.get(
    "/api/v1/assessments/schedules/{schedule_id}",
    response_model=ScheduledAssessmentResponse,
)
async def get_scheduled_assessment(
    schedule_id: str,
    current_user: CanReadAssessments,
    schedule_repository: ScheduledAssessmentRepositoryDep,
) -> ScheduledAssessmentResponse:
    schedule = schedule_repository.get_schedule(schedule_id, tenant_id=current_user.tenant_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SCHEDULED_ASSESSMENT_NOT_FOUND",
                "message": "Scheduled assessment not found",
            },
        )
    return _scheduled_assessment_response(schedule)


@app.post(
    "/api/v1/assessments/schedules/{schedule_id}/pause",
    response_model=ScheduledAssessmentResponse,
)
async def pause_scheduled_assessment(
    schedule_id: str,
    current_user: CanCreateAssessments,
    schedule_repository: ScheduledAssessmentRepositoryDep,
) -> ScheduledAssessmentResponse:
    schedule = schedule_repository.update_status(
        schedule_id=schedule_id,
        tenant_id=current_user.tenant_id,
        status=ScheduledAssessmentStatus.PAUSED,
    )
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SCHEDULED_ASSESSMENT_NOT_FOUND",
                "message": "Scheduled assessment not found",
            },
        )
    return _scheduled_assessment_response(schedule)


@app.post(
    "/api/v1/assessments/schedules/{schedule_id}/resume",
    response_model=ScheduledAssessmentResponse,
)
async def resume_scheduled_assessment(
    schedule_id: str,
    current_user: CanCreateAssessments,
    schedule_repository: ScheduledAssessmentRepositoryDep,
) -> ScheduledAssessmentResponse:
    schedule = schedule_repository.update_status(
        schedule_id=schedule_id,
        tenant_id=current_user.tenant_id,
        status=ScheduledAssessmentStatus.ACTIVE,
    )
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SCHEDULED_ASSESSMENT_NOT_FOUND",
                "message": "Scheduled assessment not found",
            },
        )
    return _scheduled_assessment_response(schedule)


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


@app.post("/api/v1/integrations/opsorchestra/pull")
async def pull_entities_from_opsorchestra(
    current_user: CanManageOrganizations,
    repository: EntityRepositoryDep,
    connector: OpsOrchestraConnectorDep,
    org_id: str | None = Query(default=None),
) -> dict[str, Any]:
    if not connector.is_graph_pull_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "OPSORCHESTRA_PULL_NOT_CONFIGURED",
                "message": "OpsOrchestra graph export URL is not configured",
            },
        )

    pulled_entities = await connector.pull_entities(
        tenant_id=current_user.tenant_id,
        org_id=org_id,
    )
    imported_counts: dict[str, int] = {}
    imported_total = 0
    for entity_group in pulled_entities.values():
        for entity in entity_group:
            repository.upsert_entity(entity, tenant_id=current_user.tenant_id)
            entity_key = str(entity.type).strip().lower()
            imported_counts[entity_key] = imported_counts.get(entity_key, 0) + 1
            imported_total += 1

    audit_log(
        AuditEventType.DATA_IMPORTED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="opsorchestra_graph_export",
        details={
            "org_id": org_id,
            "imported_total": imported_total,
            "imported_counts": imported_counts,
        },
    )
    return {
        "status": "imported",
        "source": "opsorchestra_graph_export",
        "tenant_id": current_user.tenant_id,
        "org_id": org_id,
        "imported_total": imported_total,
        "imported_counts": imported_counts,
    }


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
