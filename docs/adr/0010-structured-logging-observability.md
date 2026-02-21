# ADR-0010: Structured Logging and Observability

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore currently has no logging, metrics, or tracing implementation. As the system moves toward production:

- **Debugging**: Cannot troubleshoot issues without logs
- **Monitoring**: Cannot detect anomalies or failures
- **Auditing**: SOC2 requires audit trails for security events
- **Performance**: Cannot identify bottlenecks without metrics
- **Correlation**: Cannot trace requests across async operations

This represents a critical operational gap that blocks production deployment.

## Decision Drivers

- **SOC2 Compliance**: Audit logging is a mandatory control
- **Operability**: Production systems require observability
- **Multi-tenancy**: Logs must include tenant context
- **Security**: Sensitive data must not leak into logs
- **Correlation**: Distributed operations need request tracing
- **Cost**: Log volume and storage costs must be manageable

## Considered Options

### Option 1: structlog with OpenTelemetry

Use structlog for structured logging with OpenTelemetry for distributed tracing.

**Pros:**
- Structured JSON logs by default
- Context binding reduces boilerplate
- OpenTelemetry is CNCF standard
- Vendor-agnostic export (Jaeger, Zipkin, DataDog, etc.)
- Excellent Python integration
- Built-in security features (processors)

**Cons:**
- Learning curve for structlog patterns
- OpenTelemetry adds dependencies
- Initial configuration complexity

### Option 2: Standard Library logging

Use Python's built-in logging module with JSON formatter.

**Pros:**
- No dependencies
- Familiar to all Python developers
- Extensive documentation

**Cons:**
- Verbose configuration
- Context propagation is manual
- No built-in structured logging
- Custom code for JSON formatting

### Option 3: Loguru

Use Loguru for simplified logging.

**Pros:**
- Simple API, minimal configuration
- Built-in rotation and retention
- Colorized output

**Cons:**
- Less flexible for enterprise use
- No OpenTelemetry integration
- Limited structured logging support
- Less control over output format

### Option 4: ELK Stack Native

Direct integration with Elasticsearch using python-elasticsearch.

**Pros:**
- Direct indexing, no intermediate processing
- Rich querying capabilities

**Cons:**
- Vendor lock-in to ELK
- Complexity of managing Elasticsearch
- Overkill for startup phase

## Decision

**Use Option 1: structlog with OpenTelemetry.**

We will implement:
1. **structlog** for structured, contextual logging
2. **OpenTelemetry** for distributed tracing and metrics
3. **Correlation IDs** for request tracing
4. **Log levels** by environment (DEBUG in dev, INFO in prod)
5. **Sensitive data filtering** via processors
6. **Audit logging** for security events

Rationale:
- structlog provides clean, contextual logging patterns
- OpenTelemetry is the industry standard for observability
- Combination provides logs, metrics, and traces
- Vendor-agnostic allows future flexibility
- Supports SOC2 audit requirements

## Consequences

### Positive
- Structured JSON logs enable log aggregation and search
- Correlation IDs trace requests across async boundaries
- OpenTelemetry enables APM tool integration
- Sensitive data filtered automatically
- Audit trail for SOC2 compliance
- Performance metrics for optimization

### Negative
- Additional dependencies (structlog, opentelemetry-*)
- Initial setup and configuration time
- Developers must use structured logging patterns
- Log volume management needed

### Neutral
- Requires log aggregation infrastructure (CloudWatch, DataDog, etc.)
- Training needed for structlog patterns

## Implementation Notes

### Dependencies

```toml
# pyproject.toml
dependencies = [
    "structlog>=24.0",
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
    "opentelemetry-instrumentation-fastapi>=0.40",
    "opentelemetry-instrumentation-sqlalchemy>=0.40",
    "opentelemetry-exporter-otlp>=1.20",
]
```

### Logging Configuration

```python
# src/scalescore/core/logging.py
import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from scalescore.config import settings


def setup_logging() -> None:
    """Configure structured logging for the application."""
    
    # Determine processors based on environment
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_app_context,
        _filter_sensitive_data,
    ]
    
    if settings.is_development():
        # Development: pretty console output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # Production: JSON for log aggregation
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        level=settings.log_level,
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _add_app_context(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add application context to all logs."""
    event_dict["service"] = "scalescore"
    event_dict["version"] = settings.app_version
    event_dict["environment"] = settings.environment
    return event_dict


# Sensitive field patterns to filter
SENSITIVE_FIELDS = {
    "password",
    "secret",
    "token",
    "api_key",
    "authorization",
    "credit_card",
    "ssn",
}


def _filter_sensitive_data(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Filter sensitive data from logs."""
    return _recursive_filter(event_dict)


def _recursive_filter(data: Any) -> Any:
    """Recursively filter sensitive fields."""
    if isinstance(data, dict):
        return {
            k: "[REDACTED]" if _is_sensitive(k) else _recursive_filter(v)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [_recursive_filter(item) for item in data]
    return data


def _is_sensitive(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    key_lower = key.lower()
    return any(pattern in key_lower for pattern in SENSITIVE_FIELDS)


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a configured logger instance."""
    return structlog.get_logger(name)
```

### Correlation ID Middleware

```python
# src/scalescore/api/middleware/correlation.py
import uuid
from contextvars import ContextVar

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable for correlation ID
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")

CORRELATION_ID_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Add correlation ID to all requests for tracing."""
    
    async def dispatch(self, request: Request, call_next):
        # Get or generate correlation ID
        correlation_id = request.headers.get(
            CORRELATION_ID_HEADER,
            str(uuid.uuid4()),
        )
        
        # Store in context
        correlation_id_ctx.set(correlation_id)
        request.state.correlation_id = correlation_id
        
        # Bind to structlog context
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            path=request.url.path,
            method=request.method,
        )
        
        # Process request
        response = await call_next(request)
        
        # Add to response headers
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        
        # Clear context
        structlog.contextvars.unbind_contextvars(
            "correlation_id",
            "path",
            "method",
        )
        
        return response
```

### Request Logging Middleware

```python
# src/scalescore/api/middleware/request_logging.py
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from scalescore.core.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all API requests with timing."""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        
        # Log request
        logger.info(
            "request_started",
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        
        try:
            response = await call_next(request)
            
            # Log response
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
            
            return response
            
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "request_failed",
                error=str(e),
                duration_ms=round(duration_ms, 2),
            )
            raise
```

### OpenTelemetry Setup

```python
# src/scalescore/core/telemetry.py
from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from scalescore.config import settings


def setup_telemetry(app=None, engine=None) -> None:
    """Configure OpenTelemetry tracing and metrics."""
    
    if settings.is_development() and not settings.features.enable_telemetry:
        return  # Skip telemetry in development unless explicitly enabled
    
    # Create resource with service information
    resource = Resource.create({
        SERVICE_NAME: "scalescore",
        SERVICE_VERSION: settings.app_version,
        "deployment.environment": settings.environment,
    })
    
    # Configure tracing
    tracer_provider = TracerProvider(resource=resource)
    
    if settings.otlp_endpoint:
        span_exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    
    trace.set_tracer_provider(tracer_provider)
    
    # Configure metrics
    if settings.otlp_endpoint:
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=settings.otlp_endpoint),
            export_interval_millis=60000,
        )
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[metric_reader],
        )
        metrics.set_meter_provider(meter_provider)
    
    # Instrument FastAPI
    if app:
        FastAPIInstrumentor.instrument_app(app)
    
    # Instrument SQLAlchemy
    if engine:
        SQLAlchemyInstrumentor().instrument(engine=engine)


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer for manual instrumentation."""
    return trace.get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    """Get a meter for custom metrics."""
    return metrics.get_meter(name)
```

### Custom Metrics Example

```python
# src/scalescore/scoring/metrics.py
from opentelemetry import metrics

from scalescore.core.telemetry import get_meter

meter = get_meter("scalescore.scoring")

# Counter for assessments
assessments_counter = meter.create_counter(
    name="assessments_total",
    description="Total number of assessments run",
    unit="1",
)

# Histogram for scoring duration
scoring_duration = meter.create_histogram(
    name="scoring_duration_seconds",
    description="Time spent calculating scores",
    unit="s",
)

# Gauge for current score
current_score = meter.create_observable_gauge(
    name="current_readiness_score",
    description="Latest readiness score",
    unit="1",
    callbacks=[],  # Add callback to fetch latest score
)


def record_assessment(org_id: str, organization_id: str, score: float) -> None:
    """Record assessment metrics."""
    labels = {
        "org_id": org_id,
        "organization_id": organization_id,
    }
    assessments_counter.add(1, labels)
```

### Audit Logging

```python
# src/scalescore/core/audit.py
from datetime import datetime
from enum import Enum
from typing import Any

from scalescore.core.logging import get_logger

audit_logger = get_logger("scalescore.audit")


class AuditEventType(str, Enum):
    """Types of audit events for SOC2 compliance."""
    # Authentication
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    TOKEN_REFRESH = "auth.token.refresh"
    
    # Authorization
    ACCESS_GRANTED = "authz.access.granted"
    ACCESS_DENIED = "authz.access.denied"
    
    # Data access
    ASSESSMENT_CREATED = "data.assessment.created"
    ASSESSMENT_VIEWED = "data.assessment.viewed"
    ASSESSMENT_DELETED = "data.assessment.deleted"
    REPORT_EXPORTED = "data.report.exported"
    
    # Configuration
    CONFIG_CHANGED = "config.changed"
    USER_CREATED = "config.user.created"
    ROLE_CHANGED = "config.role.changed"


def audit_log(
    event_type: AuditEventType,
    actor_id: str,
    org_id: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    success: bool = True,
) -> None:
    """
    Record an audit event.
    
    All audit logs are written at INFO level and include:
    - Timestamp (added by structlog)
    - Correlation ID (from context)
    - Event type
    - Actor (user performing action)
    - Tenant context
    - Resource being accessed
    - Success/failure status
    - Additional details
    """
    audit_logger.info(
        event_type.value,
        audit=True,  # Flag for filtering
        actor_id=actor_id,
        org_id=org_id,
        resource_type=resource_type,
        resource_id=resource_id,
        success=success,
        details=details or {},
    )
```

### Usage Examples

```python
# In API endpoint
from scalescore.core.logging import get_logger
from scalescore.core.audit import audit_log, AuditEventType

logger = get_logger(__name__)


@router.post("/assessments")
async def create_assessment(request: AssessmentRequest, current_user: User):
    logger.info(
        "creating_assessment",
        organization_id=request.organization_id,
        entity_count=len(request.entities),
    )
    
    try:
        result = await run_assessment(request)
        
        # Audit log for compliance
        audit_log(
            event_type=AuditEventType.ASSESSMENT_CREATED,
            actor_id=current_user.id,
            org_id=current_user.org_id,
            resource_type="assessment",
            resource_id=result.id,
            details={"score": result.overall_score},
        )
        
        logger.info(
            "assessment_completed",
            assessment_id=result.id,
            score=result.overall_score,
        )
        
        return result
        
    except Exception as e:
        logger.exception("assessment_failed", error=str(e))
        raise
```

### Log Output Examples

```json
// Development (pretty printed for readability)
{
    "timestamp": "2026-01-27T10:30:00.123456Z",
    "level": "info",
    "event": "request_completed",
    "correlation_id": "abc-123-def",
    "service": "scalescore",
    "version": "0.1.0",
    "environment": "development",
    "path": "/api/v1/assessments",
    "method": "POST",
    "status_code": 200,
    "duration_ms": 45.23
}

// Audit log entry
{
    "timestamp": "2026-01-27T10:30:00.150000Z",
    "level": "info",
    "event": "data.assessment.created",
    "audit": true,
    "correlation_id": "abc-123-def",
    "actor_id": "user-456",
    "org_id": "org-789",
    "resource_type": "assessment",
    "resource_id": "assess-001",
    "success": true,
    "details": {"score": 78.5}
}
```

## Related Decisions

- ADR-0007: Error Handling Strategy (error logging integration)
- ADR-0009: Configuration Management (log level configuration)
- ADR-0011: Authentication Strategy (audit logging for auth events)

## Notes

- Configure log retention policy (recommend 90 days for operational logs, 1 year for audit logs)
- Set up alerts for error rate thresholds
- Consider log sampling in high-volume production environments
- Audit logs may need separate storage for compliance
