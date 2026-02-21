# ADR-0007: Error Handling Strategy

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore currently uses raw Python exceptions (primarily `ValueError`) throughout the codebase for error handling. As the system scales to handle multiple tenants and integrates with external systems (OpsOrchestra, client applications), we need a structured approach to:

- Define consistent error types across domain boundaries
- Return meaningful API error responses with stable error codes
- Prevent information leakage in production (security requirement)
- Enable proper error logging and monitoring
- Support internationalization of error messages

Current state analysis shows 7+ instances of `ValueError` in csv_connector.py alone, with no structured error hierarchy or consistent response format.

## Decision Drivers

- **Security-First**: Errors must not leak internal implementation details, stack traces, or sensitive data in production
- **Developer Experience**: Clear error types and codes for debugging and client integration
- **Operability**: Errors must be loggable, traceable, and monitorable
- **Multi-tenancy**: Errors must include tenant context without cross-tenant information leakage
- **API Stability**: Error codes provide stable contract even when messages change

## Considered Options

### Option 1: Structured Exception Hierarchy with Error Codes

Create a custom exception hierarchy with domain-specific exceptions, each carrying a unique error code, and centralized FastAPI exception handlers.

**Pros:**
- Clear domain semantics (e.g., `AssessmentNotFoundError` vs generic `NotFoundError`)
- Stable error codes for client integration
- Centralized handling reduces boilerplate
- Easy to add logging and metrics
- Supports different detail levels per environment

**Cons:**
- Initial setup overhead
- Developers must learn and use custom exceptions
- Risk of exception proliferation if not managed

### Option 2: Generic HTTP Exceptions Only

Use FastAPI's built-in `HTTPException` throughout the codebase.

**Pros:**
- No custom code needed
- FastAPI handles serialization automatically
- Simple to understand

**Cons:**
- No domain semantics
- No stable error codes
- Cannot differentiate error types programmatically
- Difficult to add cross-cutting concerns (logging, metrics)
- Business logic coupled to HTTP layer

### Option 3: Result Types (Either/Result Pattern)

Use a Result type pattern (like `Result[T, E]`) throughout the codebase.

**Pros:**
- Explicit error handling, no exceptions
- Functional programming benefits
- No hidden control flow

**Cons:**
- Major paradigm shift for Python developers
- Verbose code with constant unwrapping
- Poor ecosystem support in Python
- Doesn't integrate well with FastAPI's exception-based model

## Decision

**Implement Option 1: Structured Exception Hierarchy with Error Codes.**

We will create a layered exception hierarchy:

1. **Base Exceptions**: `ScaleScoreError` as root, with `DomainError`, `InfrastructureError`, `ValidationError`
2. **Domain Exceptions**: Specific exceptions per domain area (assessment, scoring, tenancy)
3. **Error Codes**: Each exception type has a unique, stable error code
4. **API Response Format**: Consistent JSON structure with code, message, and optional details
5. **Environment-Aware Details**: Full details in development, sanitized in production

Rationale:
- Aligns with FastAPI's exception handling model
- Provides clear contract for API consumers
- Enables comprehensive logging and monitoring
- Supports SOC2 requirements for audit trails
- Minimal overhead once established

## Consequences

### Positive
- Consistent error responses across all API endpoints
- Stable error codes enable reliable client error handling
- Centralized exception handling simplifies adding logging/metrics
- Security: Production errors sanitized automatically
- Clear domain language in codebase

### Negative
- Initial migration effort to replace existing `ValueError` usage
- Developers must learn exception hierarchy
- Slight code overhead for raising domain exceptions

### Neutral
- Requires documentation of all error codes for API consumers
- Exception classes add to codebase size

## Implementation Notes

### Exception Hierarchy

```python
# src/scalescore/core/exceptions.py
from enum import Enum
from typing import Any

class ErrorCode(str, Enum):
    """Stable error codes for API consumers."""
    # Validation errors (1xxx)
    VALIDATION_ERROR = "SCALE_1000"
    MISSING_REQUIRED_FIELD = "SCALE_1001"
    INVALID_FIELD_VALUE = "SCALE_1002"
    INVALID_CSV_FORMAT = "SCALE_1003"
    
    # Assessment errors (2xxx)
    ASSESSMENT_NOT_FOUND = "SCALE_2000"
    ASSESSMENT_ALREADY_EXISTS = "SCALE_2001"
    ASSESSMENT_INVALID_STATE = "SCALE_2002"
    
    # Organization errors (3xxx)
    ORGANIZATION_NOT_FOUND = "SCALE_3000"
    ORGANIZATION_REQUIRED = "SCALE_3001"
    MULTIPLE_ORGANIZATIONS_NOT_SUPPORTED = "SCALE_3002"
    
    # Tenant/Auth errors (4xxx)
    TENANT_ACCESS_DENIED = "SCALE_4000"
    TENANT_NOT_FOUND = "SCALE_4001"
    AUTHENTICATION_REQUIRED = "SCALE_4002"
    INSUFFICIENT_PERMISSIONS = "SCALE_4003"
    
    # Infrastructure errors (5xxx)
    DATABASE_ERROR = "SCALE_5000"
    EXTERNAL_SERVICE_ERROR = "SCALE_5001"
    CONFIGURATION_ERROR = "SCALE_5002"
    
    # Internal errors (9xxx)
    INTERNAL_ERROR = "SCALE_9000"
    NOT_IMPLEMENTED = "SCALE_9001"


class ScaleScoreError(Exception):
    """Base exception for all ScaleScore errors."""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.cause = cause
    
    def to_dict(self, include_details: bool = False) -> dict[str, Any]:
        """Serialize to dictionary for API response."""
        result = {
            "code": self.code.value,
            "message": self.message,
        }
        if include_details and self.details:
            result["details"] = self.details
        return result


class ValidationError(ScaleScoreError):
    """Raised when input validation fails."""
    
    def __init__(
        self,
        message: str,
        field: str | None = None,
        code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        details: dict[str, Any] | None = None,
    ):
        details = details or {}
        if field:
            details["field"] = field
        super().__init__(message, code, details)
        self.field = field


class AssessmentNotFoundError(ScaleScoreError):
    """Raised when an assessment cannot be found."""
    
    def __init__(self, assessment_id: str):
        super().__init__(
            message=f"Assessment not found: {assessment_id}",
            code=ErrorCode.ASSESSMENT_NOT_FOUND,
            details={"assessment_id": assessment_id},
        )
        self.assessment_id = assessment_id


class TenantAccessDeniedError(ScaleScoreError):
    """Raised when access to a tenant resource is denied."""
    
    def __init__(self, org_id: str, resource_type: str, resource_id: str):
        super().__init__(
            message="Access denied to requested resource",
            code=ErrorCode.TENANT_ACCESS_DENIED,
            details={
                "org_id": org_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
            },
        )


class OrganizationRequiredError(ScaleScoreError):
    """Raised when at least one organization is required."""
    
    def __init__(self):
        super().__init__(
            message="At least one organization is required for assessment",
            code=ErrorCode.ORGANIZATION_REQUIRED,
        )
```

### FastAPI Exception Handlers

```python
# src/scalescore/api/exception_handlers.py
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from scalescore.core.exceptions import ScaleScoreError, ErrorCode
from scalescore.config import settings

logger = logging.getLogger(__name__)


async def scalescore_exception_handler(
    request: Request,
    exc: ScaleScoreError,
) -> JSONResponse:
    """Handle all ScaleScore domain exceptions."""
    # Log with full context
    logger.error(
        "Domain error occurred",
        extra={
            "error_code": exc.code.value,
            "error_message": exc.message,
            "error_details": exc.details,
            "path": request.url.path,
            "method": request.method,
            "correlation_id": getattr(request.state, "correlation_id", None),
        },
        exc_info=exc.cause,
    )
    
    # Determine HTTP status code from error code category
    status_code = _get_status_code(exc.code)
    
    # Include details only in development
    include_details = settings.environment == "development"
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.to_dict(include_details=include_details),
        },
    )


async def pydantic_exception_handler(
    request: Request,
    exc: PydanticValidationError,
) -> JSONResponse:
    """Convert Pydantic validation errors to our format."""
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": "Request validation failed",
                "details": {"errors": errors} if settings.environment == "development" else {},
            },
        },
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Catch-all for unhandled exceptions."""
    logger.exception(
        "Unhandled exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "correlation_id": getattr(request.state, "correlation_id", None),
        },
    )
    
    # Never expose internal details in production
    message = (
        str(exc) if settings.environment == "development"
        else "An internal error occurred"
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": message,
            },
        },
    )


def _get_status_code(code: ErrorCode) -> int:
    """Map error codes to HTTP status codes."""
    code_mapping = {
        # 400 Bad Request
        ErrorCode.VALIDATION_ERROR: 400,
        ErrorCode.MISSING_REQUIRED_FIELD: 400,
        ErrorCode.INVALID_FIELD_VALUE: 400,
        ErrorCode.INVALID_CSV_FORMAT: 400,
        ErrorCode.ORGANIZATION_REQUIRED: 400,
        ErrorCode.MULTIPLE_ORGANIZATIONS_NOT_SUPPORTED: 400,
        
        # 401 Unauthorized
        ErrorCode.AUTHENTICATION_REQUIRED: 401,
        
        # 403 Forbidden
        ErrorCode.TENANT_ACCESS_DENIED: 403,
        ErrorCode.INSUFFICIENT_PERMISSIONS: 403,
        
        # 404 Not Found
        ErrorCode.ASSESSMENT_NOT_FOUND: 404,
        ErrorCode.ORGANIZATION_NOT_FOUND: 404,
        ErrorCode.TENANT_NOT_FOUND: 404,
        
        # 409 Conflict
        ErrorCode.ASSESSMENT_ALREADY_EXISTS: 409,
        ErrorCode.ASSESSMENT_INVALID_STATE: 409,
        
        # 500 Internal Server Error
        ErrorCode.DATABASE_ERROR: 500,
        ErrorCode.EXTERNAL_SERVICE_ERROR: 502,
        ErrorCode.CONFIGURATION_ERROR: 500,
        ErrorCode.INTERNAL_ERROR: 500,
        
        # 501 Not Implemented
        ErrorCode.NOT_IMPLEMENTED: 501,
    }
    return code_mapping.get(code, 500)
```

### Registering Handlers

```python
# src/scalescore/api/main.py
from fastapi import FastAPI
from pydantic import ValidationError as PydanticValidationError

from scalescore.core.exceptions import ScaleScoreError
from scalescore.api.exception_handlers import (
    scalescore_exception_handler,
    pydantic_exception_handler,
    unhandled_exception_handler,
)

app = FastAPI(title="ScaleScore API", version="0.1.0")

# Register exception handlers
app.add_exception_handler(ScaleScoreError, scalescore_exception_handler)
app.add_exception_handler(PydanticValidationError, pydantic_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
```

### Migration Example

```python
# BEFORE (csv_connector.py)
raise ValueError(f"Missing required columns: {', '.join(missing)}")

# AFTER
from scalescore.core.exceptions import ValidationError, ErrorCode

raise ValidationError(
    message=f"Missing required columns: {', '.join(missing)}",
    code=ErrorCode.INVALID_CSV_FORMAT,
    details={"missing_columns": list(missing)},
)
```

### API Response Examples

```json
// Development environment
{
    "error": {
        "code": "SCALE_1003",
        "message": "Missing required columns: headcount_current, revenue_current",
        "details": {
            "missing_columns": ["headcount_current", "revenue_current"]
        }
    }
}

// Production environment
{
    "error": {
        "code": "SCALE_1003",
        "message": "Missing required columns: headcount_current, revenue_current"
    }
}
```

## Related Decisions

- ADR-0001: Pydantic v2 for Models (Pydantic validation errors integrated)
- ADR-0002: FastAPI for API Layer (exception handlers)
- ADR-0010: Structured Logging and Observability (error logging integration)
- ADR-0011: Authentication Strategy (auth-related errors)

## Notes

- Error codes should be documented in the API reference for client developers
- Consider adding error code constants to the OpenAPI spec
- Migration should be done module by module to ensure consistency
