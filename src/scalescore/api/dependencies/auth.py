from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from scalescore.config import settings
from scalescore.core.audit import audit_access_denied
from scalescore.core.auth.external_oidc import get_external_oidc_auth_service
from scalescore.core.auth.jwt import JWTService, TokenPayload
from scalescore.core.auth.opsorchestra import get_opsorchestra_auth_service
from scalescore.core.auth.roles import Permission, get_permissions
from scalescore.core.exceptions import AuthenticationError, ScaleScoreError
from scalescore.storage.auth_repository import SQLiteAuthRepository, get_auth_repository

security = HTTPBearer(auto_error=False)
api_key_security = APIKeyHeader(name="X-API-Key", auto_error=False)


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
        auth_method="dev",
    )


Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
APIKeyCredentials = Annotated[str | None, Depends(api_key_security)]
JWTServiceDep = Annotated[JWTService, Depends(get_jwt_service)]
AuthRepositoryDep = Annotated[SQLiteAuthRepository, Depends(get_auth_repository)]


async def get_current_user(
    credentials: Credentials,
    api_key: APIKeyCredentials,
    jwt_service: JWTServiceDep,
    auth_repository: AuthRepositoryDep,
) -> TokenPayload:
    if settings.is_development() and settings.auth.skip_auth:
        return _get_dev_user()

    if credentials:
        token = credentials.credentials
        try:
            return jwt_service.verify_token(token)
        except AuthenticationError as err:
            auth_error = err
            if settings.integration.external_oidc_auth_enabled:
                try:
                    external_oidc_auth = get_external_oidc_auth_service()
                except ValueError as config_err:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={
                            "code": "EXTERNAL_OIDC_AUTH_NOT_CONFIGURED",
                            "message": str(config_err),
                        },
                    ) from config_err
                try:
                    return external_oidc_auth.verify_token(token)
                except AuthenticationError as external_error:
                    auth_error = external_error
                except ScaleScoreError as external_error:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=external_error.to_dict(include_details=settings.is_development()),
                    ) from external_error
            if settings.integration.opsorchestra_auth_enabled:
                try:
                    opsorchestra_auth = get_opsorchestra_auth_service()
                except ValueError as config_err:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={
                            "code": "OPSORCHESTRA_AUTH_NOT_CONFIGURED",
                            "message": str(config_err),
                        },
                    ) from config_err
                try:
                    return opsorchestra_auth.verify_parent_token(token)
                except AuthenticationError as ops_error:
                    auth_error = ops_error
                except ScaleScoreError as ops_error:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=ops_error.to_dict(include_details=settings.is_development()),
                    ) from ops_error
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=auth_error.to_dict(),
                headers={"WWW-Authenticate": "Bearer"},
            ) from auth_error

    if api_key:
        try:
            principal = auth_repository.authenticate_api_key(api_key)
            return TokenPayload(
                sub=principal.user_id,
                tenant_id=principal.tenant_id,
                email=principal.email,
                roles=principal.roles,
                exp=principal.expires_at or datetime(2099, 12, 31, tzinfo=UTC),
                iat=datetime.now(UTC),
                auth_method="api_key",
            )
        except AuthenticationError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=err.to_dict(),
                headers={"WWW-Authenticate": "Bearer"},
            ) from err

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "AUTHENTICATION_REQUIRED",
            "message": "Missing Bearer token or X-API-Key header",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


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
