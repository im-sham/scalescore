"""
Audit logging for SOC2 compliance.

This module provides audit logging for security-sensitive operations.
Audit logs are separate from operational logs and should be retained
according to compliance requirements (typically 1+ year).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from scalescore.core.logging import get_logger

_audit_logger = get_logger("scalescore.audit")


class AuditEventType(StrEnum):
    """Types of audit events for SOC2 compliance."""

    # Authentication events
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    TOKEN_REFRESH = "auth.token.refresh"
    PASSWORD_CHANGE = "auth.password.change"
    PASSWORD_RESET_REQUEST = "auth.password.reset_request"

    # Authorization events
    ACCESS_GRANTED = "authz.access.granted"
    ACCESS_DENIED = "authz.access.denied"
    PERMISSION_CHANGE = "authz.permission.change"

    # Data access events
    ASSESSMENT_CREATED = "data.assessment.created"
    ASSESSMENT_VIEWED = "data.assessment.viewed"
    ASSESSMENT_DELETED = "data.assessment.deleted"
    REPORT_GENERATED = "data.report.generated"
    REPORT_EXPORTED = "data.report.exported"
    DATA_IMPORTED = "data.import"
    DATA_EXPORTED = "data.export"

    # Configuration events
    CONFIG_CHANGED = "config.changed"
    USER_CREATED = "config.user.created"
    USER_UPDATED = "config.user.updated"
    USER_DELETED = "config.user.deleted"
    ROLE_CHANGED = "config.role.changed"
    TENANT_CREATED = "config.tenant.created"

    # System events
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    MAINTENANCE_MODE = "system.maintenance"


def audit_log(
    event_type: AuditEventType,
    *,
    actor_id: str | None = None,
    tenant_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """
    Record an audit event.

    All audit logs include:
    - Timestamp (ISO format)
    - Event type
    - Actor (user performing action)
    - Tenant context
    - Resource being accessed
    - Success/failure status
    - IP address (when available)

    Args:
        event_type: Type of audit event
        actor_id: User ID performing the action
        tenant_id: Tenant context
        resource_type: Type of resource being accessed
        resource_id: ID of resource being accessed
        success: Whether the operation succeeded
        details: Additional context
        ip_address: Client IP address
    """
    _audit_logger.info(
        event_type.value,
        audit=True,
        event_type=event_type.value,
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        success=success,
        ip_address=ip_address,
        details=details or {},
        audit_timestamp=datetime.now(UTC).isoformat(),
    )


def audit_login_success(
    user_id: str,
    tenant_id: str,
    ip_address: str | None = None,
) -> None:
    """Record successful login."""
    audit_log(
        AuditEventType.LOGIN_SUCCESS,
        actor_id=user_id,
        tenant_id=tenant_id,
        ip_address=ip_address,
    )


def audit_login_failure(
    email: str,
    reason: str,
    ip_address: str | None = None,
) -> None:
    """Record failed login attempt."""
    audit_log(
        AuditEventType.LOGIN_FAILURE,
        success=False,
        details={"email": email, "reason": reason},
        ip_address=ip_address,
    )


def audit_access_denied(
    user_id: str,
    tenant_id: str,
    resource_type: str,
    resource_id: str,
    reason: str,
) -> None:
    """Record access denial."""
    audit_log(
        AuditEventType.ACCESS_DENIED,
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        success=False,
        details={"reason": reason},
    )


def audit_assessment_created(
    user_id: str,
    tenant_id: str,
    assessment_id: str,
    organization_id: str,
) -> None:
    """Record assessment creation."""
    audit_log(
        AuditEventType.ASSESSMENT_CREATED,
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="assessment",
        resource_id=assessment_id,
        details={"organization_id": organization_id},
    )


def audit_data_export(
    user_id: str,
    tenant_id: str,
    export_type: str,
    record_count: int,
) -> None:
    """Record data export."""
    audit_log(
        AuditEventType.DATA_EXPORTED,
        actor_id=user_id,
        tenant_id=tenant_id,
        resource_type="export",
        details={"export_type": export_type, "record_count": record_count},
    )
