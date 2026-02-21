from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from scalescore.config import settings
from scalescore.core.audit import audit_access_denied
from scalescore.core.auth.jwt import JWTService, TokenPayload
from scalescore.core.auth.roles import Permission, get_permissions
from scalescore.core.exceptions import AuthenticationError

security = HTTPBearer(auto_error=False)


@lru_cache
def get_jwt_service() -> JWTService:
    return JWTService()


def _get_dev_user() -> TokenPayload:
    return TokenPayload(
        sub="dev-user-1",
        tenant_id="dev-tenant",
        email="dev@example.com",
        roles=["admin"],
        exp=datetime(2099, 12, 31, tzinfo=UTC),
        iat=datetime.now(UTC),
    )


Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
JWTServiceDep = Annotated[JWTService, Depends(get_jwt_service)]


async def get_current_user(
    credentials: Credentials,
    jwt_service: JWTServiceDep,
) -> TokenPayload:
    if settings.is_development() and settings.auth.skip_auth:
        return _get_dev_user()

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTHENTICATION_REQUIRED", "message": "Missing authorization header"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return jwt_service.verify_token(credentials.credentials)
    except AuthenticationError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=err.to_dict(),
            headers={"WWW-Authenticate": "Bearer"},
        ) from err


CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]


class RequirePermission:
    def __init__(self, permission: Permission) -> None:
        self.permission = permission

    async def __call__(self, current_user: CurrentUser) -> TokenPayload:
        user_permissions = get_permissions(current_user.roles)
        if self.permission not in user_permissions:
            audit_access_denied(
                user_id=current_user.sub,
                tenant_id=current_user.tenant_id,
                resource_type="permission",
                resource_id=self.permission.value,
                reason="missing_required_permission",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_PERMISSIONS",
                    "message": f"Missing required permission: {self.permission.value}",
                },
            )
        return current_user


def get_tenant_id(current_user: CurrentUser) -> str:
    return current_user.tenant_id
