# ADR-0012: Background Job Processing

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore currently processes all operations synchronously within API request handlers. This creates problems:

- **Timeouts**: Large assessments with many entities may exceed API timeout limits
- **Blocking**: Long-running calculations block the API thread
- **No Scheduling**: Cannot run periodic assessments or scheduled reports
- **No Retry**: Failed operations cannot be automatically retried
- **No Progress**: Users cannot track progress of long-running operations

As organizations scale (1000+ entities) and we add features like scheduled assessments and webhook notifications, synchronous processing becomes untenable.

## Decision Drivers

- **Reliability**: Jobs should survive server restarts
- **Scalability**: Workers should scale independently of API
- **Observability**: Job status and progress must be trackable
- **Simplicity**: Solution should match current team size and complexity
- **Cost**: Infrastructure costs should be reasonable
- **Multi-tenancy**: Jobs must maintain tenant context

## Considered Options

### Option 1: Celery with Redis

Use Celery task queue with Redis as message broker.

**Pros:**
- Mature, battle-tested (10+ years)
- Excellent Python integration
- Built-in retry, scheduling, monitoring
- Redis is simple to operate
- Large community and documentation
- Flower provides web UI for monitoring

**Cons:**
- Additional infrastructure (Redis, workers)
- Celery can be complex to configure
- Memory usage for large result sets

### Option 2: RQ (Redis Queue)

Simpler Redis-based job queue.

**Pros:**
- Very simple API
- Minimal configuration
- Python-native

**Cons:**
- Fewer features than Celery
- No built-in scheduling (need rq-scheduler)
- Smaller ecosystem
- Less suitable for complex workflows

### Option 3: AWS SQS + Lambda

Serverless approach with AWS services.

**Pros:**
- No infrastructure to manage
- Automatic scaling
- Pay-per-use

**Cons:**
- AWS vendor lock-in
- Cold start latency
- Complex local development
- 15-minute execution limit

### Option 4: PostgreSQL-backed Queue (pgqueue)

Use PostgreSQL as job queue with SKIP LOCKED.

**Pros:**
- No additional infrastructure
- Transactional consistency with data
- Simple setup

**Cons:**
- Database as queue is an anti-pattern at scale
- Polling overhead
- No native scheduling
- Limited ecosystem

### Option 5: Temporal.io

Durable workflow orchestration platform.

**Pros:**
- Powerful workflow primitives
- Built-in retries and timeouts
- Excellent for complex workflows
- Strong consistency guarantees

**Cons:**
- Significant infrastructure complexity
- Steep learning curve
- Overkill for current needs
- Larger operational overhead

## Decision

**Use Option 1: Celery with Redis.**

We will implement:
1. **Celery** for task queue and scheduling
2. **Redis** as message broker
3. **Async Tasks**: Assessment processing, report generation
4. **Scheduled Tasks**: Periodic health checks, scheduled assessments
5. **Task Status API**: Track job progress
6. **Tenant-Aware Tasks**: Maintain tenant context in workers

Rationale:
- Celery is the industry standard for Python background jobs
- Redis is already needed for caching (ADR-0018)
- Mature ecosystem with proven reliability
- Good balance of features and complexity
- Excellent documentation and community support

## Consequences

### Positive
- Long-running assessments won't timeout
- API remains responsive during heavy processing
- Failed jobs automatically retry
- Scheduled assessments possible
- Independent worker scaling
- Job monitoring and observability

### Negative
- Additional infrastructure (Redis, Celery workers)
- Operational complexity increases
- Must handle distributed system concerns
- Development environment more complex

### Neutral
- Requires Redis infrastructure
- Workers need deployment configuration
- Monitoring tools needed (Flower)

## Implementation Notes

### Dependencies

```toml
# pyproject.toml
dependencies = [
    "celery[redis]>=5.3",
    "redis>=5.0",
    "flower>=2.0",  # Optional: monitoring UI
]
```

### Celery Configuration

```python
# src/scalescore/core/celery_app.py
from celery import Celery
from kombu import Exchange, Queue

from scalescore.config import settings

# Create Celery application
celery_app = Celery(
    "scalescore",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
)

# Configure Celery
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # Timezone
    timezone="UTC",
    enable_utc=True,
    
    # Task execution
    task_acks_late=True,  # Acknowledge after completion
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # Fair distribution
    
    # Result backend
    result_expires=86400,  # 24 hours
    
    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
    
    # Queues
    task_queues=(
        Queue("default", Exchange("default"), routing_key="default"),
        Queue("assessments", Exchange("assessments"), routing_key="assessments"),
        Queue("reports", Exchange("reports"), routing_key="reports"),
        Queue("scheduled", Exchange("scheduled"), routing_key="scheduled"),
    ),
    task_default_queue="default",
    
    # Task routing
    task_routes={
        "scalescore.tasks.assessments.*": {"queue": "assessments"},
        "scalescore.tasks.reports.*": {"queue": "reports"},
        "scalescore.tasks.scheduled.*": {"queue": "scheduled"},
    },
    
    # Beat schedule (for periodic tasks)
    beat_schedule={
        "health-check-every-5-minutes": {
            "task": "scalescore.tasks.scheduled.health_check",
            "schedule": 300.0,  # 5 minutes
        },
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks([
    "scalescore.tasks.assessments",
    "scalescore.tasks.reports",
    "scalescore.tasks.scheduled",
])
```

### Base Task with Tenant Context

```python
# src/scalescore/core/celery_base.py
from celery import Task
from typing import Any
import structlog

from scalescore.core.celery_app import celery_app
from scalescore.core.logging import get_logger

logger = get_logger(__name__)


class OrgAwareTask(Task):
    """Base task class that maintains org context."""
    
    # Retry settings
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600  # Max 10 minutes between retries
    retry_jitter = True
    
    def before_start(self, task_id: str, args: tuple, kwargs: dict):
        """Set up context before task execution."""
        org_id = kwargs.get("org_id")
        
        # Bind logging context
        structlog.contextvars.bind_contextvars(
            task_id=task_id,
            task_name=self.name,
            org_id=org_id,
        )
        
        logger.info(
            "task_started",
            args=args,
            kwargs={k: v for k, v in kwargs.items() if k != "org_id"},
        )
    
    def after_return(
        self,
        status: str,
        retval: Any,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ):
        """Clean up after task completion."""
        logger.info(
            "task_completed",
            status=status,
            has_error=einfo is not None,
        )
        
        # Clear logging context
        structlog.contextvars.unbind_contextvars(
            "task_id",
            "task_name",
            "org_id",
        )
    
    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ):
        """Handle task failure."""
        logger.exception(
            "task_failed",
            error=str(exc),
            retries=self.request.retries,
            max_retries=self.max_retries,
        )
    
    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ):
        """Log retry attempt."""
        logger.warning(
            "task_retrying",
            error=str(exc),
            retry_count=self.request.retries + 1,
            max_retries=self.max_retries,
        )
```

### Assessment Tasks

```python
# src/scalescore/tasks/assessments.py
from celery import shared_task
from datetime import datetime
from typing import Any

from scalescore.core.celery_base import OrgAwareTask
from scalescore.core.celery_app import celery_app
from scalescore.core.logging import get_logger
from scalescore.scoring.engine import ScoringEngine
from scalescore.repositories.assessment import AssessmentRepository

logger = get_logger(__name__)


@celery_app.task(
    base=OrgAwareTask,
    bind=True,
    name="scalescore.tasks.assessments.run_async_assessment",
    max_retries=3,
)
def run_async_assessment(
    self,
    assessment_id: str,
    org_id: str,
    organization_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Run assessment asynchronously.
    
    Args:
        assessment_id: Unique ID for this assessment job
        org_id: Organization context
        organization_data: Serialized assessment input data
    
    Returns:
        Assessment result as dictionary
    """
    logger.info(
        "running_assessment",
        assessment_id=assessment_id,
        entity_count=len(organization_data.get("entities", [])),
    )
    
    try:
        # Update status to processing
        repo = AssessmentRepository()
        repo.update_status(
            assessment_id=assessment_id,
            org_id=org_id,
            status="processing",
            progress=0,
        )
        
        # Run scoring engine
        engine = ScoringEngine()
        
        # Update progress during processing
        def progress_callback(progress: int, message: str):
            repo.update_status(
                assessment_id=assessment_id,
                org_id=org_id,
                status="processing",
                progress=progress,
                message=message,
            )
        
        result = engine.calculate_readiness(
            organization_data=organization_data,
            progress_callback=progress_callback,
        )
        
        # Save result
        repo.save_result(
            assessment_id=assessment_id,
            org_id=org_id,
            result=result.model_dump(),
        )
        
        # Update status to completed
        repo.update_status(
            assessment_id=assessment_id,
            org_id=org_id,
            status="completed",
            progress=100,
            completed_at=datetime.utcnow(),
        )
        
        logger.info(
            "assessment_completed",
            assessment_id=assessment_id,
            score=result.overall_score,
        )
        
        return result.model_dump()
        
    except Exception as e:
        # Update status to failed
        repo.update_status(
            assessment_id=assessment_id,
            org_id=org_id,
            status="failed",
            error=str(e),
        )
        
        logger.exception(
            "assessment_failed",
            assessment_id=assessment_id,
        )
        
        # Re-raise for retry
        raise


@celery_app.task(
    base=OrgAwareTask,
    name="scalescore.tasks.assessments.cancel_assessment",
)
def cancel_assessment(assessment_id: str, org_id: str) -> bool:
    """Cancel a running assessment."""
    from scalescore.core.celery_app import celery_app
    
    # Revoke the task
    celery_app.control.revoke(assessment_id, terminate=True)
    
    # Update status
    repo = AssessmentRepository()
    repo.update_status(
        assessment_id=assessment_id,
        org_id=org_id,
        status="cancelled",
    )
    
    return True
```

### Task Status Model

```python
# src/scalescore/models/task.py
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of an async task."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskInfo(BaseModel):
    """Information about an async task."""
    task_id: str
    org_id: str
    status: TaskStatus
    progress: int = Field(ge=0, le=100, default=0)
    message: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    @property
    def is_terminal(self) -> bool:
        """Check if task is in terminal state."""
        return self.status in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
```

### API Endpoints for Async Jobs

```python
# src/scalescore/api/v1/assessments.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from uuid import uuid4

from scalescore.api.dependencies.auth import get_current_user, get_org_id
from scalescore.tasks.assessments import run_async_assessment
from scalescore.models.task import TaskInfo
from scalescore.repositories.task import TaskRepository

router = APIRouter()


@router.post("/assessments/async", response_model=TaskInfo)
async def create_async_assessment(
    request: AssessmentRequest,
    org_id: str = Depends(get_org_id),
) -> TaskInfo:
    """
    Start an asynchronous assessment.
    
    Returns immediately with a task_id that can be polled for status.
    """
    task_id = str(uuid4())
    
    # Create initial task record
    task_repo = TaskRepository()
    task_info = task_repo.create_task(
        task_id=task_id,
        org_id=org_id,
        task_type="assessment",
    )
    
    # Queue the task
    run_async_assessment.apply_async(
        kwargs={
            "assessment_id": task_id,
            "org_id": org_id,
            "organization_data": request.model_dump(),
        },
        task_id=task_id,
    )
    
    return task_info


@router.get("/assessments/async/{task_id}", response_model=TaskInfo)
async def get_assessment_status(
    task_id: str,
    org_id: str = Depends(get_org_id),
) -> TaskInfo:
    """Get status of an async assessment."""
    task_repo = TaskRepository()
    task_info = task_repo.get_task(task_id=task_id, org_id=org_id)
    
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task_info


@router.delete("/assessments/async/{task_id}")
async def cancel_async_assessment(
    task_id: str,
    org_id: str = Depends(get_org_id),
) -> dict:
    """Cancel a running assessment."""
    from scalescore.tasks.assessments import cancel_assessment
    
    cancel_assessment.delay(
        assessment_id=task_id,
        org_id=org_id,
    )
    
    return {"message": "Cancellation requested", "task_id": task_id}
```

### Scheduled Tasks

```python
# src/scalescore/tasks/scheduled.py
from celery import shared_task
from celery.schedules import crontab

from scalescore.core.celery_app import celery_app
from scalescore.core.logging import get_logger
from scalescore.repositories.scheduled_assessment import ScheduledAssessmentRepository

logger = get_logger(__name__)


@celery_app.task(name="scalescore.tasks.scheduled.health_check")
def health_check():
    """Periodic health check task."""
    logger.info("health_check_running")
    # Check database connectivity, redis, etc.
    return {"status": "healthy"}


@celery_app.task(name="scalescore.tasks.scheduled.run_scheduled_assessments")
def run_scheduled_assessments():
    """Run all due scheduled assessments."""
    repo = ScheduledAssessmentRepository()
    due_assessments = repo.get_due_assessments()
    
    for schedule in due_assessments:
        from scalescore.tasks.assessments import run_async_assessment
        
        run_async_assessment.delay(
            assessment_id=f"scheduled-{schedule.id}",
            org_id=schedule.org_id,
            organization_data=schedule.assessment_config,
        )
        
        repo.mark_executed(schedule.id)
    
    return {"processed": len(due_assessments)}


# Add to beat schedule in celery_app.py
# "run-scheduled-assessments": {
#     "task": "scalescore.tasks.scheduled.run_scheduled_assessments",
#     "schedule": crontab(minute="*/15"),  # Every 15 minutes
# },
```

### Docker Compose for Development

```yaml
# docker-compose.yml
version: "3.8"

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  celery-worker:
    build: .
    command: celery -A scalescore.core.celery_app worker --loglevel=info
    volumes:
      - .:/app
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
    depends_on:
      - redis

  celery-beat:
    build: .
    command: celery -A scalescore.core.celery_app beat --loglevel=info
    volumes:
      - .:/app
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
    depends_on:
      - redis

  flower:
    image: mher/flower
    command: celery --broker=redis://redis:6379/0 flower --port=5555
    ports:
      - "5555:5555"
    depends_on:
      - redis

volumes:
  redis_data:
```

### CLI Commands

```python
# src/scalescore/cli/worker.py
import click


@click.group()
def worker():
    """Celery worker management commands."""
    pass


@worker.command()
@click.option("--queues", "-Q", default="default", help="Queues to process")
@click.option("--concurrency", "-c", default=4, help="Worker concurrency")
def start(queues: str, concurrency: int):
    """Start Celery worker."""
    from scalescore.core.celery_app import celery_app
    
    argv = [
        "worker",
        f"--queues={queues}",
        f"--concurrency={concurrency}",
        "--loglevel=info",
    ]
    celery_app.worker_main(argv)


@worker.command()
def beat():
    """Start Celery beat scheduler."""
    from scalescore.core.celery_app import celery_app
    
    celery_app.Beat().run()
```

## Related Decisions

- ADR-0009: Configuration Management (Celery configuration)
- ADR-0010: Structured Logging and Observability (task logging)
- ADR-0018: Caching Strategy (Redis infrastructure shared)

## Notes

- Monitor Redis memory usage as result backend can grow
- Consider result expiration settings for storage management
- Implement dead letter queue for failed tasks
- Add Flower to production for task monitoring
- Consider task priorities for urgent assessments
