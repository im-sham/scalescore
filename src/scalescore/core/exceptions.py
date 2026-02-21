"""
Structured exception hierarchy for ScaleScore.

This module implements ADR-0007: Error Handling Strategy.

All domain exceptions inherit from ScaleScoreError and carry:
- A unique error code (SCALE_XXXX) for API consumers
- A human-readable message
- Optional details for debugging
- Optional cause for exception chaining

Usage:
    from scalescore.core.exceptions import ValidationError, ErrorCode

    raise ValidationError(
        message="Missing required columns",
        code=ErrorCode.INVALID_CSV_FORMAT,
        details={"missing_columns": ["headcount", "revenue"]},
    )
"""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """
    Stable error codes for API consumers.

    Code ranges:
    - 1xxx: Validation errors
    - 2xxx: Assessment errors
    - 3xxx: Organization/Entity errors
    - 4xxx: Authentication/Authorization errors
    - 5xxx: Infrastructure errors
    - 9xxx: Internal/Unknown errors
    """

    # Validation errors (1xxx)
    VALIDATION_ERROR = "SCALE_1000"
    MISSING_REQUIRED_FIELD = "SCALE_1001"
    INVALID_FIELD_VALUE = "SCALE_1002"
    INVALID_CSV_FORMAT = "SCALE_1003"
    INVALID_DATE_FORMAT = "SCALE_1004"
    SCHEMA_VALIDATION_FAILED = "SCALE_1005"

    # Assessment errors (2xxx)
    ASSESSMENT_NOT_FOUND = "SCALE_2000"
    ASSESSMENT_ALREADY_EXISTS = "SCALE_2001"
    ASSESSMENT_INVALID_STATE = "SCALE_2002"
    ASSESSMENT_PROCESSING_FAILED = "SCALE_2003"

    # Organization/Entity errors (3xxx)
    ORGANIZATION_NOT_FOUND = "SCALE_3000"
    ORGANIZATION_REQUIRED = "SCALE_3001"
    MULTIPLE_ORGANIZATIONS_NOT_SUPPORTED = "SCALE_3002"
    ENTITY_NOT_FOUND = "SCALE_3003"
    DUPLICATE_ENTITY = "SCALE_3004"

    # Tenant/Auth errors (4xxx)
    TENANT_ACCESS_DENIED = "SCALE_4000"
    TENANT_NOT_FOUND = "SCALE_4001"
    AUTHENTICATION_REQUIRED = "SCALE_4002"
    INSUFFICIENT_PERMISSIONS = "SCALE_4003"
    TOKEN_EXPIRED = "SCALE_4004"
    INVALID_TOKEN = "SCALE_4005"
    INVALID_CREDENTIALS = "SCALE_4006"
    INVALID_REFRESH_TOKEN = "SCALE_4007"
    REFRESH_TOKEN_EXPIRED = "SCALE_4008"
    TOKEN_REUSE_DETECTED = "SCALE_4009"
    INVALID_API_KEY = "SCALE_4010"
    API_KEY_EXPIRED = "SCALE_4011"

    # Infrastructure errors (5xxx)
    DATABASE_ERROR = "SCALE_5000"
    EXTERNAL_SERVICE_ERROR = "SCALE_5001"
    CONFIGURATION_ERROR = "SCALE_5002"
    FILE_NOT_FOUND = "SCALE_5003"
    FILE_READ_ERROR = "SCALE_5004"

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
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.cause = cause
        if cause:
            self.__cause__ = cause

    def to_dict(self, include_details: bool = False) -> dict[str, Any]:
        """Serialize to dictionary for API response."""
        result: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
        }
        if include_details and self.details:
            result["details"] = self.details
        return result

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code.value!r}, message={self.message!r})"


# =============================================================================
# Validation Errors (1xxx)
# =============================================================================


class ValidationError(ScaleScoreError):
    """Raised when input validation fails."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or {}
        if field:
            details["field"] = field
        super().__init__(message, code, details)
        self.field = field


class MissingRequiredFieldError(ValidationError):
    """Raised when a required field is missing."""

    def __init__(self, field: str, entity_type: str | None = None) -> None:
        details: dict[str, Any] = {"field": field}
        if entity_type:
            details["entity_type"] = entity_type
        super().__init__(
            message=f"Missing required field: {field}",
            field=field,
            code=ErrorCode.MISSING_REQUIRED_FIELD,
            details=details,
        )


class InvalidFieldValueError(ValidationError):
    """Raised when a field has an invalid value."""

    def __init__(
        self,
        field: str,
        value: Any,
        expected: str | None = None,
    ) -> None:
        details: dict[str, Any] = {"field": field, "received": str(value)}
        if expected:
            details["expected"] = expected
        super().__init__(
            message=f"Invalid value for field '{field}'",
            field=field,
            code=ErrorCode.INVALID_FIELD_VALUE,
            details=details,
        )


class CSVFormatError(ValidationError):
    """Raised when CSV format is invalid."""

    def __init__(
        self,
        message: str,
        missing_columns: list[str] | None = None,
        unexpected_columns: list[str] | None = None,
        file_path: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if missing_columns:
            details["missing_columns"] = missing_columns
        if unexpected_columns:
            details["unexpected_columns"] = unexpected_columns
        if file_path:
            details["file_path"] = file_path
        super().__init__(
            message=message,
            code=ErrorCode.INVALID_CSV_FORMAT,
            details=details,
        )


# =============================================================================
# Assessment Errors (2xxx)
# =============================================================================


class AssessmentNotFoundError(ScaleScoreError):
    """Raised when an assessment cannot be found."""

    def __init__(self, assessment_id: str) -> None:
        super().__init__(
            message=f"Assessment not found: {assessment_id}",
            code=ErrorCode.ASSESSMENT_NOT_FOUND,
            details={"assessment_id": assessment_id},
        )
        self.assessment_id = assessment_id


class AssessmentExistsError(ScaleScoreError):
    """Raised when trying to create an assessment that already exists."""

    def __init__(self, assessment_id: str) -> None:
        super().__init__(
            message=f"Assessment already exists: {assessment_id}",
            code=ErrorCode.ASSESSMENT_ALREADY_EXISTS,
            details={"assessment_id": assessment_id},
        )
        self.assessment_id = assessment_id


class AssessmentProcessingError(ScaleScoreError):
    """Raised when assessment processing fails."""

    def __init__(self, message: str, assessment_id: str | None = None) -> None:
        details: dict[str, Any] = {}
        if assessment_id:
            details["assessment_id"] = assessment_id
        super().__init__(
            message=message,
            code=ErrorCode.ASSESSMENT_PROCESSING_FAILED,
            details=details,
        )


# =============================================================================
# Organization/Entity Errors (3xxx)
# =============================================================================


class OrganizationNotFoundError(ScaleScoreError):
    """Raised when an organization cannot be found."""

    def __init__(self, organization_id: str) -> None:
        super().__init__(
            message=f"Organization not found: {organization_id}",
            code=ErrorCode.ORGANIZATION_NOT_FOUND,
            details={"organization_id": organization_id},
        )
        self.organization_id = organization_id


class OrganizationRequiredError(ScaleScoreError):
    """Raised when at least one organization is required."""

    def __init__(self) -> None:
        super().__init__(
            message="At least one organization is required for assessment",
            code=ErrorCode.ORGANIZATION_REQUIRED,
        )


class MultipleOrganizationsError(ScaleScoreError):
    """Raised when multiple organizations provided but only one supported."""

    def __init__(self, count: int) -> None:
        super().__init__(
            message=f"Assessment supports a single organization, received {count}",
            code=ErrorCode.MULTIPLE_ORGANIZATIONS_NOT_SUPPORTED,
            details={"organization_count": count},
        )


class EntityNotFoundError(ScaleScoreError):
    """Raised when a generic entity cannot be found."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        super().__init__(
            message=f"{entity_type} not found: {entity_id}",
            code=ErrorCode.ENTITY_NOT_FOUND,
            details={"entity_type": entity_type, "entity_id": entity_id},
        )
        self.entity_type = entity_type
        self.entity_id = entity_id


# =============================================================================
# Authentication/Authorization Errors (4xxx)
# =============================================================================


class AuthenticationError(ScaleScoreError):
    """Raised when authentication fails."""

    def __init__(
        self,
        message: str = "Authentication required",
        code: ErrorCode = ErrorCode.AUTHENTICATION_REQUIRED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code, details)


class AuthorizationError(ScaleScoreError):
    """Raised when authorization fails."""

    def __init__(
        self,
        message: str = "Insufficient permissions",
        code: ErrorCode = ErrorCode.INSUFFICIENT_PERMISSIONS,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code, details)


class TenantAccessDeniedError(AuthorizationError):
    """Raised when access to a tenant resource is denied."""

    def __init__(
        self,
        tenant_id: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        details: dict[str, Any] = {"tenant_id": tenant_id}
        if resource_type:
            details["resource_type"] = resource_type
        if resource_id:
            details["resource_id"] = resource_id
        super().__init__(
            message="Access denied to requested resource",
            code=ErrorCode.TENANT_ACCESS_DENIED,
            details=details,
        )


# =============================================================================
# Infrastructure Errors (5xxx)
# =============================================================================


class DatabaseError(ScaleScoreError):
    """Raised when a database operation fails."""

    def __init__(
        self,
        message: str = "Database operation failed",
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.DATABASE_ERROR,
            cause=cause,
        )


class FileNotFoundError(ScaleScoreError):
    """Raised when a required file is not found."""

    def __init__(self, file_path: str) -> None:
        super().__init__(
            message=f"File not found: {file_path}",
            code=ErrorCode.FILE_NOT_FOUND,
            details={"file_path": file_path},
        )
        self.file_path = file_path


class ConfigurationError(ScaleScoreError):
    """Raised when configuration is invalid."""

    def __init__(self, message: str, setting: str | None = None) -> None:
        details: dict[str, Any] = {}
        if setting:
            details["setting"] = setting
        super().__init__(
            message=message,
            code=ErrorCode.CONFIGURATION_ERROR,
            details=details,
        )
