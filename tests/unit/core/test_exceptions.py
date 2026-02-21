"""Tests for error handling (ADR-0007)."""

import pytest

from scalescore.core.exceptions import (
    AssessmentNotFoundError,
    AuthenticationError,
    AuthorizationError,
    CSVFormatError,
    ErrorCode,
    MissingRequiredFieldError,
    MultipleOrganizationsError,
    OrganizationRequiredError,
    ScaleScoreError,
    TenantAccessDeniedError,
    ValidationError,
)


class TestErrorCode:
    """Test error code enumeration."""

    def test_error_codes_are_strings(self) -> None:
        assert isinstance(ErrorCode.VALIDATION_ERROR.value, str)
        assert ErrorCode.VALIDATION_ERROR.value == "SCALE_1000"

    def test_error_code_ranges(self) -> None:
        assert ErrorCode.VALIDATION_ERROR.value.startswith("SCALE_1")
        assert ErrorCode.ASSESSMENT_NOT_FOUND.value.startswith("SCALE_2")
        assert ErrorCode.ORGANIZATION_NOT_FOUND.value.startswith("SCALE_3")
        assert ErrorCode.TENANT_ACCESS_DENIED.value.startswith("SCALE_4")
        assert ErrorCode.DATABASE_ERROR.value.startswith("SCALE_5")
        assert ErrorCode.INTERNAL_ERROR.value.startswith("SCALE_9")


class TestScaleScoreError:
    """Test base exception class."""

    def test_basic_creation(self) -> None:
        error = ScaleScoreError("Something went wrong")

        assert error.message == "Something went wrong"
        assert error.code == ErrorCode.INTERNAL_ERROR
        assert error.details == {}
        assert error.cause is None

    def test_with_code_and_details(self) -> None:
        error = ScaleScoreError(
            message="Validation failed",
            code=ErrorCode.VALIDATION_ERROR,
            details={"field": "email"},
        )

        assert error.code == ErrorCode.VALIDATION_ERROR
        assert error.details == {"field": "email"}

    def test_to_dict_without_details(self) -> None:
        error = ScaleScoreError(
            message="Test error",
            code=ErrorCode.INTERNAL_ERROR,
            details={"secret": "value"},
        )

        result = error.to_dict(include_details=False)

        assert result == {
            "code": "SCALE_9000",
            "message": "Test error",
        }
        assert "details" not in result

    def test_to_dict_with_details(self) -> None:
        error = ScaleScoreError(
            message="Test error",
            code=ErrorCode.INTERNAL_ERROR,
            details={"field": "email"},
        )

        result = error.to_dict(include_details=True)

        assert result["details"] == {"field": "email"}

    def test_str_representation(self) -> None:
        error = ScaleScoreError("Test error", code=ErrorCode.VALIDATION_ERROR)

        assert str(error) == "[SCALE_1000] Test error"

    def test_exception_chaining(self) -> None:
        cause = ValueError("Original error")
        error = ScaleScoreError("Wrapped error", cause=cause)

        assert error.cause is cause
        assert error.__cause__ is cause


class TestValidationError:
    """Test validation error hierarchy."""

    def test_basic_validation_error(self) -> None:
        error = ValidationError("Invalid input")

        assert error.code == ErrorCode.VALIDATION_ERROR
        assert error.field is None

    def test_validation_error_with_field(self) -> None:
        error = ValidationError("Invalid email", field="email")

        assert error.field == "email"
        assert error.details["field"] == "email"

    def test_missing_required_field_error(self) -> None:
        error = MissingRequiredFieldError(field="username")

        assert error.code == ErrorCode.MISSING_REQUIRED_FIELD
        assert error.field == "username"
        assert "username" in error.message

    def test_csv_format_error(self) -> None:
        error = CSVFormatError(
            message="Missing columns",
            missing_columns=["id", "name"],
            file_path="/data/test.csv",
        )

        assert error.code == ErrorCode.INVALID_CSV_FORMAT
        assert error.details["missing_columns"] == ["id", "name"]
        assert error.details["file_path"] == "/data/test.csv"


class TestAssessmentErrors:
    """Test assessment-related errors."""

    def test_assessment_not_found(self) -> None:
        error = AssessmentNotFoundError("assess-123")

        assert error.code == ErrorCode.ASSESSMENT_NOT_FOUND
        assert error.assessment_id == "assess-123"
        assert "assess-123" in error.message

    def test_organization_required(self) -> None:
        error = OrganizationRequiredError()

        assert error.code == ErrorCode.ORGANIZATION_REQUIRED
        assert "organization" in error.message.lower()

    def test_multiple_organizations_error(self) -> None:
        error = MultipleOrganizationsError(count=3)

        assert error.code == ErrorCode.MULTIPLE_ORGANIZATIONS_NOT_SUPPORTED
        assert error.details["organization_count"] == 3


class TestAuthErrors:
    """Test authentication/authorization errors."""

    def test_authentication_error(self) -> None:
        error = AuthenticationError()

        assert error.code == ErrorCode.AUTHENTICATION_REQUIRED

    def test_authorization_error(self) -> None:
        error = AuthorizationError()

        assert error.code == ErrorCode.INSUFFICIENT_PERMISSIONS

    def test_tenant_access_denied(self) -> None:
        error = TenantAccessDeniedError(
            tenant_id="tenant-123",
            resource_type="assessment",
            resource_id="assess-456",
        )

        assert error.code == ErrorCode.TENANT_ACCESS_DENIED
        assert error.details["tenant_id"] == "tenant-123"
        assert error.details["resource_type"] == "assessment"
        assert "Access denied" in error.message


class TestExceptionHandlerIntegration:
    """Test exception handlers work correctly."""

    def test_exception_is_catchable_by_base_class(self) -> None:
        with pytest.raises(ScaleScoreError):
            raise ValidationError("test")

    def test_validation_error_is_catchable_by_validation_class(self) -> None:
        with pytest.raises(ValidationError):
            raise MissingRequiredFieldError(field="test")

    def test_auth_error_is_catchable_by_auth_class(self) -> None:
        with pytest.raises(AuthorizationError):
            raise TenantAccessDeniedError(tenant_id="test")
