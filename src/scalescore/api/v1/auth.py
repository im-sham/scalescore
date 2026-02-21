from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr

from scalescore.api.dependencies.auth import get_current_user, get_jwt_service
from scalescore.config import settings
from scalescore.core.audit import (
    AuditEventType,
    audit_log,
    audit_login_failure,
    audit_login_success,
)
from scalescore.core.auth.jwt import JWTService, TokenPayload
from scalescore.core.auth.refresh import RefreshTokenService, get_sqlite_refresh_token_repository
from scalescore.core.exceptions import AuthenticationError

router = APIRouter(prefix="/auth", tags=["auth"])


def get_refresh_service(
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
) -> RefreshTokenService:
    repository = get_sqlite_refresh_token_repository()
    return RefreshTokenService(repository=repository, jwt_service=jwt_service)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


JWTServiceDep = Annotated[JWTService, Depends(get_jwt_service)]
RefreshServiceDep = Annotated[RefreshTokenService, Depends(get_refresh_service)]
CurrentUserDep = Annotated[TokenPayload, Depends(get_current_user)]


def _request_ip(request: Request) -> str | None:
    if request.client:
        return request.client.host
    return None


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    jwt_service: JWTServiceDep,
    refresh_service: RefreshServiceDep,
) -> TokenResponse:
    user = _authenticate_user(payload.email, payload.password)
    if not user:
        audit_login_failure(
            email=payload.email,
            reason="invalid_credentials",
            ip_address=_request_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
        )

    access_token = jwt_service.create_access_token(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        roles=user["roles"],
    )
    refresh_token = refresh_service.create_refresh_token(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        roles=user["roles"],
    )
    audit_login_success(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        ip_address=_request_ip(request),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.auth.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    payload: RefreshRequest,
    refresh_service: RefreshServiceDep,
) -> TokenResponse:
    try:
        access_token, new_refresh_token = refresh_service.rotate_refresh_token(
            payload.refresh_token
        )
    except AuthenticationError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=err.to_dict(),
        ) from err

    token_payload = refresh_service.jwt_service.verify_token(access_token)
    audit_log(
        AuditEventType.TOKEN_REFRESH,
        actor_id=token_payload.sub,
        tenant_id=token_payload.tenant_id,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.auth.access_token_expire_minutes * 60,
    )


@router.post("/logout")
async def logout(
    payload: LogoutRequest,
    current_user: CurrentUserDep,
    refresh_service: RefreshServiceDep,
) -> dict[str, str]:
    if payload.refresh_token:
        refresh_service.revoke_token(payload.refresh_token)
    audit_log(
        AuditEventType.LOGOUT,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
    )
    return {"message": "Logged out successfully"}


def _authenticate_user(email: str, password: str) -> dict | None:
    if settings.is_development() and email == "dev@example.com" and password == "dev":
        return {
            "id": "dev-user-1",
            "tenant_id": "dev-tenant",
            "email": "dev@example.com",
            "roles": ["admin"],
        }
    return None
