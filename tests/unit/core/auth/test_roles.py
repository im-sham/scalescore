
from scalescore.core.auth.roles import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    get_permissions,
)


class TestPermission:
    def test_permissions_are_strings(self) -> None:
        assert Permission.ASSESSMENT_CREATE == "assessment:create"
        assert Permission.REPORT_VIEW == "report:view"

    def test_all_permissions_exist(self) -> None:
        expected = [
            "assessment:create",
            "assessment:read",
            "assessment:delete",
            "report:view",
            "report:export",
            "organization:manage",
            "user:manage",
            "user:view",
            "system:config",
            "audit:view",
        ]
        actual = [p.value for p in Permission]
        assert sorted(actual) == sorted(expected)


class TestRole:
    def test_roles_are_strings(self) -> None:
        assert Role.VIEWER == "viewer"
        assert Role.ANALYST == "analyst"
        assert Role.ADMIN == "admin"
        assert Role.SUPER_ADMIN == "super_admin"

    def test_all_roles_exist(self) -> None:
        expected = ["viewer", "analyst", "admin", "super_admin"]
        actual = [r.value for r in Role]
        assert sorted(actual) == sorted(expected)


class TestRolePermissions:
    def test_viewer_has_read_only_permissions(self) -> None:
        perms = ROLE_PERMISSIONS[Role.VIEWER]
        assert Permission.ASSESSMENT_READ in perms
        assert Permission.REPORT_VIEW in perms
        assert Permission.ASSESSMENT_CREATE not in perms

    def test_analyst_can_create_assessments(self) -> None:
        perms = ROLE_PERMISSIONS[Role.ANALYST]
        assert Permission.ASSESSMENT_CREATE in perms
        assert Permission.ASSESSMENT_READ in perms
        assert Permission.REPORT_EXPORT in perms
        assert Permission.ASSESSMENT_DELETE not in perms

    def test_admin_can_manage_users(self) -> None:
        perms = ROLE_PERMISSIONS[Role.ADMIN]
        assert Permission.USER_MANAGE in perms
        assert Permission.ASSESSMENT_DELETE in perms
        assert Permission.SYSTEM_CONFIG not in perms

    def test_super_admin_has_all_permissions(self) -> None:
        perms = ROLE_PERMISSIONS[Role.SUPER_ADMIN]
        for perm in Permission:
            assert perm in perms


class TestGetPermissions:
    def test_returns_permissions_for_single_role(self) -> None:
        perms = get_permissions(["viewer"])
        assert Permission.ASSESSMENT_READ in perms
        assert Permission.ASSESSMENT_CREATE not in perms

    def test_combines_permissions_for_multiple_roles(self) -> None:
        perms = get_permissions(["viewer", "analyst"])
        assert Permission.ASSESSMENT_READ in perms
        assert Permission.ASSESSMENT_CREATE in perms
        assert Permission.REPORT_EXPORT in perms

    def test_ignores_invalid_roles(self) -> None:
        perms = get_permissions(["viewer", "nonexistent_role"])
        assert Permission.ASSESSMENT_READ in perms
        assert len(perms) == len(ROLE_PERMISSIONS[Role.VIEWER])

    def test_returns_empty_set_for_no_roles(self) -> None:
        perms = get_permissions([])
        assert len(perms) == 0

    def test_returns_empty_set_for_all_invalid_roles(self) -> None:
        perms = get_permissions(["fake", "invalid"])
        assert len(perms) == 0
