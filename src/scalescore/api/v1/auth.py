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
from scalescore.core.auth.roles import Role
from scalescore.core.exceptions import AuthenticationError, ErrorCode
from scalescore.core.rate_limit import RateLimiter, RateLimiterUnavailable, get_rate_limiter
from scalescore.storage.auth_repository import (
    APIKeyRecord,
    SQLiteAuthRepository,
    UserRecord,
    get_auth_repository,
)

router = APIRouter(prefix="/auth", tags=["auth"])

VALID_ROLE_VALUES = {role.value for role in Role}
PUBLIC_SIGNUP_ROLE_VALUES = {Role.VIEWER.value, Role.ANALYST.value}


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
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def _request_ip(request: Request) -> str | None:
    if request.client:
        return request.client.host
    return None


async def _enforce_rate_limit(
    *,
    rate_limiter: RateLimiter,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    try:
        decision = await rate_limiter.allow(
            key,
            limit=limit,
            window_seconds=window_seconds,
        )
    except RateLimiterUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "RATE_LIMITER_UNAVAILABLE",
                "message": "Rate limiting service unavailable",
            },
        ) from None

    if decision.allowed:
        return

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "RATE_LIMITED",
            "message": "Rate limit exceeded, retry later",
            "retry_after_seconds": decision.retry_after_seconds,
        },
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def _normalize_roles(roles: list[str], *, empty_code: str) -> list[str]:
    normalized: list[str] = []
    invalid_roles: list[str] = []
    for role in roles:
        role_value = role.strip()
        if role_value not in VALID_ROLE_VALUES:
            invalid_roles.append(role)
            continue
        if role_value not in normalized:
            normalized.append(role_value)

    if invalid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_ROLE",
                "message": "One or more roles are not recognized",
                "roles": invalid_roles,
            },
        )
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": empty_code, "message": "At least one role is required"},
        )
    return normalized


def _signup_roles(roles: list[str]) -> list[str]:
    normalized = _normalize_roles(roles, empty_code="SIGNUP_ROLE_REQUIRED")
    elevated_roles = sorted(set(normalized) - PUBLIC_SIGNUP_ROLE_VALUES)
    if elevated_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ELEVATED_SIGNUP_ROLE_NOT_ALLOWED",
                "message": "Public signup cannot grant elevated roles",
                "roles": elevated_roles,
            },
        )
    return normalized


def _api_key_roles(
    requested_roles: list[str] | None,
    current_roles: list[str],
) -> list[str]:
    if requested_roles is None:
        return _normalize_roles(current_roles, empty_code="API_KEY_ROLE_REQUIRED")

    normalized = _normalize_roles(requested_roles, empty_code="API_KEY_ROLE_REQUIRED")
    current_role_set = set(_normalize_roles(current_roles, empty_code="CURRENT_ROLE_REQUIRED"))
    requested_role_set = set(normalized)
    if not requested_role_set.issubset(current_role_set):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "API_KEY_ROLE_ESCALATION_NOT_ALLOWED",
                "message": "API key roles must be a subset of the current principal roles",
                "roles": sorted(requested_role_set - current_role_set),
            },
        )
    return normalized


def _enforce_api_key_creation_allowed(
    *,
    payload: CreateAPIKeyRequest,
    current_user: TokenPayload,
) -> None:
    if current_user.auth_method == "api_key":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "API_KEY_DELEGATION_NOT_ALLOWED",
                "message": "API keys cannot create child API keys",
            },
        )
    if payload.expires_in_days is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "NON_EXPIRING_API_KEYS_NOT_ALLOWED",
                "message": "API keys must have an explicit expiry",
            },
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    jwt_service: JWTServiceDep,
    refresh_service: RefreshServiceDep,
    auth_repository: AuthRepositoryDep,
    rate_limiter: RateLimiterDep,
) -> TokenResponse:
    ip_address = _request_ip(request) or "unknown"
    await _enforce_rate_limit(
        rate_limiter=rate_limiter,
        key=f"auth:login:{payload.email.lower()}:{ip_address}",
        limit=settings.auth.login_rate_limit_requests,
        window_seconds=settings.auth.login_rate_limit_window_seconds,
    )

    user = auth_repository.authenticate_user(payload.email, payload.password)
    if not user:
        audit_login_failure(
            email=payload.email,
            reason="invalid_credentials",
            ip_address=ip_address,
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
        ip_address=ip_address,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.auth.access_token_expire_minutes * 60,
    )


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    request: Request,
    auth_repository: AuthRepositoryDep,
    rate_limiter: RateLimiterDep,
) -> UserResponse:
    ip_address = _request_ip(request) or "unknown"
    await _enforce_rate_limit(
        rate_limiter=rate_limiter,
        key=f"auth:signup:{ip_address}",
        limit=settings.auth.signup_rate_limit_requests,
        window_seconds=settings.auth.signup_rate_limit_window_seconds,
    )

    if settings.is_production() and not settings.auth.public_signup_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PUBLIC_SIGNUP_DISABLED",
                "message": "Public signup is disabled in production",
            },
        )
    signup_roles = _signup_roles(payload.roles)

    try:
        user = auth_repository.create_user(
            email=payload.email,
            password=payload.password,
            tenant_id=payload.tenant_id,
            org_id=payload.org_id,
            roles=signup_roles,
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
    request: Request,
    rate_limiter: RateLimiterDep,
) -> TokenResponse:
    ip_address = _request_ip(request) or "unknown"
    await _enforce_rate_limit(
        rate_limiter=rate_limiter,
        key=f"auth:refresh:{ip_address}",
        limit=settings.auth.refresh_rate_limit_requests,
        window_seconds=settings.auth.refresh_rate_limit_window_seconds,
    )

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
    request: Request,
    current_user: CurrentUserDep,
    auth_repository: AuthRepositoryDep,
    rate_limiter: RateLimiterDep,
) -> APIKeyCreateResponse:
    _enforce_api_key_creation_allowed(payload=payload, current_user=current_user)
    key_roles = _api_key_roles(payload.roles, current_user.roles)
    await _enforce_rate_limit(
        rate_limiter=rate_limiter,
        key=(
            f"auth:api_key_create:{current_user.tenant_id}:"
            f"{current_user.sub}:{_request_ip(request) or 'unknown'}"
        ),
        limit=settings.auth.api_key_create_rate_limit_requests,
        window_seconds=settings.auth.api_key_create_rate_limit_window_seconds,
    )
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
