from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

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
from scalescore.core.exceptions import AuthenticationError, ErrorCode
from scalescore.storage.auth_repository import (
    APIKeyRecord,
    SQLiteAuthRepository,
    UserRecord,
    get_auth_repository,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_refresh_service(
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
) -> RefreshTokenService:
    repository = get_sqlite_refresh_token_repository()
    return RefreshTokenService(repository=repository, jwt_service=jwt_service)


def _user_response(user: UserRecord) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        org_id=user.org_id,
        email=user.email,
        roles=user.roles,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def _api_key_response(api_key: APIKeyRecord) -> APIKeyResponse:
    return APIKeyResponse(
        key_id=api_key.key_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        roles=api_key.roles,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=3, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    org_id: str | None = Field(default=None, min_length=1, max_length=128)
    roles: list[str] = Field(default_factory=lambda: ["analyst"])


class UserResponse(BaseModel):
    user_id: str
    tenant_id: str
    org_id: str | None
    email: EmailStr
    roles: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class CreateAPIKeyRequest(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)
    roles: list[str] | None = None


class APIKeyResponse(BaseModel):
    key_id: str
    name: str
    key_prefix: str
    roles: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class APIKeyCreateResponse(APIKeyResponse):
    api_key: str


JWTServiceDep = Annotated[JWTService, Depends(get_jwt_service)]
RefreshServiceDep = Annotated[RefreshTokenService, Depends(get_refresh_service)]
CurrentUserDep = Annotated[TokenPayload, Depends(get_current_user)]
AuthRepositoryDep = Annotated[SQLiteAuthRepository, Depends(get_auth_repository)]


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
    auth_repository: AuthRepositoryDep,
) -> TokenResponse:
    user = auth_repository.authenticate_user(payload.email, payload.password)
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
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=user.roles,
    )
    refresh_token = refresh_service.create_refresh_token(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=user.roles,
    )
    audit_login_success(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        ip_address=_request_ip(request),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.auth.access_token_expire_minutes * 60,
    )


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    auth_repository: AuthRepositoryDep,
) -> UserResponse:
    try:
        user = auth_repository.create_user(
            email=payload.email,
            password=payload.password,
            tenant_id=payload.tenant_id,
            org_id=payload.org_id,
            roles=payload.roles,
        )
    except AuthenticationError as err:
        status_code = (
            status.HTTP_409_CONFLICT
            if err.code == ErrorCode.DUPLICATE_ENTITY
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=err.to_dict()) from err

    audit_log(
        AuditEventType.USER_CREATED,
        actor_id=user.user_id,
        tenant_id=user.tenant_id,
        resource_type="user",
        resource_id=user.user_id,
        details={"email": user.email},
    )
    return _user_response(user)


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: CurrentUserDep,
    auth_repository: AuthRepositoryDep,
) -> UserResponse:
    user = auth_repository.get_user(current_user.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User no longer exists"},
        )
    return _user_response(user)


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


@router.post("/api-keys", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: CreateAPIKeyRequest,
    current_user: CurrentUserDep,
    auth_repository: AuthRepositoryDep,
) -> APIKeyCreateResponse:
    key_roles = payload.roles or current_user.roles
    api_key_record, raw_api_key = auth_repository.create_api_key(
        user_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        name=payload.name,
        roles=key_roles,
        expires_in_days=payload.expires_in_days,
    )

    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="api_key",
        resource_id=api_key_record.key_id,
    )

    base = _api_key_response(api_key_record)
    return APIKeyCreateResponse(**base.model_dump(), api_key=raw_api_key)


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: CurrentUserDep,
    auth_repository: AuthRepositoryDep,
) -> list[APIKeyResponse]:
    keys = auth_repository.list_api_keys_for_user(current_user.sub)
    return [_api_key_response(key) for key in keys]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    current_user: CurrentUserDep,
    auth_repository: AuthRepositoryDep,
) -> dict[str, str]:
    revoked = auth_repository.revoke_api_key(key_id=key_id, user_id=current_user.sub)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "API_KEY_NOT_FOUND", "message": "API key was not found"},
        )
    audit_log(
        AuditEventType.CONFIG_CHANGED,
        actor_id=current_user.sub,
        tenant_id=current_user.tenant_id,
        resource_type="api_key",
        resource_id=key_id,
    )
    return {"message": "API key revoked"}
