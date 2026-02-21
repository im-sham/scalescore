"""
FastAPI exception handlers for ScaleScore.

This module implements the exception handling portion of ADR-0007.

Exception handlers convert domain exceptions to HTTP responses with:
- Appropriate HTTP status codes
- Consistent error response format
- Environment-aware detail exposure (full in dev, sanitized in prod)
- Structured logging of all errors
"""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from scalescore.config import settings
from scalescore.core.exceptions import (
    ErrorCode,
    ScaleScoreError,
)
from scalescore.core.logging import get_logger

logger = get_logger(__name__)


async def scalescore_exception_handler(
    request: Request,
    exc: ScaleScoreError,
) -> JSONResponse:
    """Handle all ScaleScore domain exceptions."""
    status_code = _get_status_code(exc.code)
    include_details = settings.is_development() or settings.is_testing()

    logger.warning(
        "domain_error",
        error_code=exc.code.value,
        error_message=exc.message,
        status_code=status_code,
        exc_info=exc.cause if exc.cause else None,
    )

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
    return _validation_error_response(exc.errors())


async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Convert FastAPI request validation errors to our format."""
    return _validation_error_response(exc.errors())


def _validation_error_response(errors_data: list[dict]) -> JSONResponse:
    """Build standardized response payload for request/schema validation failures."""
    include_details = settings.is_development() or settings.is_testing()

    errors = []
    for error in errors_data:
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })

    content: dict = {
        "error": {
            "code": ErrorCode.SCHEMA_VALIDATION_FAILED.value,
            "message": "Request validation failed",
        },
    }

    if include_details:
        content["error"]["details"] = {"errors": errors}

    return JSONResponse(status_code=422, content=content)


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Catch-all for unhandled exceptions."""
    include_details = settings.is_development() or settings.is_testing()

    logger.exception(
        "unhandled_exception",
        error_type=type(exc).__name__,
        error=str(exc),
    )

    message = str(exc) if include_details else "An internal error occurred"

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
    mapping: dict[ErrorCode, int] = {
        # 400 Bad Request
        ErrorCode.VALIDATION_ERROR: 400,
        ErrorCode.MISSING_REQUIRED_FIELD: 400,
        ErrorCode.INVALID_FIELD_VALUE: 400,
        ErrorCode.INVALID_CSV_FORMAT: 400,
        ErrorCode.INVALID_DATE_FORMAT: 400,
        ErrorCode.SCHEMA_VALIDATION_FAILED: 422,
        ErrorCode.ORGANIZATION_REQUIRED: 400,
        ErrorCode.MULTIPLE_ORGANIZATIONS_NOT_SUPPORTED: 400,
        # 401 Unauthorized
        ErrorCode.AUTHENTICATION_REQUIRED: 401,
        ErrorCode.TOKEN_EXPIRED: 401,
        ErrorCode.INVALID_TOKEN: 401,
        ErrorCode.INVALID_CREDENTIALS: 401,
        ErrorCode.INVALID_REFRESH_TOKEN: 401,
        ErrorCode.REFRESH_TOKEN_EXPIRED: 401,
        ErrorCode.TOKEN_REUSE_DETECTED: 401,
        # 403 Forbidden
        ErrorCode.TENANT_ACCESS_DENIED: 403,
        ErrorCode.INSUFFICIENT_PERMISSIONS: 403,
        ErrorCode.TENANT_NOT_FOUND: 403,
        # 404 Not Found
        ErrorCode.ASSESSMENT_NOT_FOUND: 404,
        ErrorCode.ORGANIZATION_NOT_FOUND: 404,
        ErrorCode.ENTITY_NOT_FOUND: 404,
        ErrorCode.FILE_NOT_FOUND: 404,
        # 409 Conflict
        ErrorCode.ASSESSMENT_ALREADY_EXISTS: 409,
        ErrorCode.ASSESSMENT_INVALID_STATE: 409,
        ErrorCode.DUPLICATE_ENTITY: 409,
        # 500 Internal Server Error
        ErrorCode.DATABASE_ERROR: 500,
        ErrorCode.CONFIGURATION_ERROR: 500,
        ErrorCode.ASSESSMENT_PROCESSING_FAILED: 500,
        ErrorCode.INTERNAL_ERROR: 500,
        # 501 Not Implemented
        ErrorCode.NOT_IMPLEMENTED: 501,
        # 502 Bad Gateway
        ErrorCode.EXTERNAL_SERVICE_ERROR: 502,
        # 503 Service Unavailable (file read errors)
        ErrorCode.FILE_READ_ERROR: 503,
    }
    return mapping.get(code, 500)


def register_exception_handlers(app) -> None:
    """Register all exception handlers with the FastAPI app."""
    app.add_exception_handler(ScaleScoreError, scalescore_exception_handler)
    app.add_exception_handler(PydanticValidationError, pydantic_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
