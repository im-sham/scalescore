from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    ASSESSMENT_CREATE = "assessment:create"
    ASSESSMENT_READ = "assessment:read"
    ASSESSMENT_DELETE = "assessment:delete"
    REPORT_VIEW = "report:view"
    REPORT_EXPORT = "report:export"
    ORGANIZATION_MANAGE = "organization:manage"
    USER_MANAGE = "user:manage"
    USER_VIEW = "user:view"
    SYSTEM_CONFIG = "system:config"
    AUDIT_VIEW = "audit:view"


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.VIEWER: {
        Permission.ASSESSMENT_READ,
        Permission.REPORT_VIEW,
    },
    Role.ANALYST: {
        Permission.ASSESSMENT_CREATE,
        Permission.ASSESSMENT_READ,
        Permission.REPORT_VIEW,
        Permission.REPORT_EXPORT,
    },
    Role.ADMIN: {
        Permission.ASSESSMENT_CREATE,
        Permission.ASSESSMENT_READ,
        Permission.ASSESSMENT_DELETE,
        Permission.REPORT_VIEW,
        Permission.REPORT_EXPORT,
        Permission.ORGANIZATION_MANAGE,
        Permission.USER_MANAGE,
        Permission.USER_VIEW,
        Permission.AUDIT_VIEW,
    },
    Role.SUPER_ADMIN: set(Permission),
}


def get_permissions(roles: list[str]) -> set[Permission]:
    permissions: set[Permission] = set()
    for role_name in roles:
        try:
            role = Role(role_name)
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        except ValueError:
            continue
    return permissions
