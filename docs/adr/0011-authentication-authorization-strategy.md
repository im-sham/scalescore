# ADR-0011: Authentication and Authorization Strategy

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore currently has no authentication or authorization. All API endpoints are publicly accessible. This represents a critical security gap that:

- Blocks production deployment
- Prevents multi-tenant data isolation
- Violates SOC2 requirements for access control
- Prevents OpsOrchestra integration (which requires authenticated context)

We need to implement:
- **Authentication**: Verify user identity
- **Authorization**: Control access to resources based on roles and tenant
- **Session Management**: Secure token handling with refresh capability
- **Tenant Isolation**: Ensure users can only access their tenant's data

## Decision Drivers

- **Security-First**: Authentication is the primary security boundary
- **Multi-tenancy**: Must support tenant isolation from day one
- **SOC2 Compliance**: Access control is a critical control
- **OpsOrchestra Integration**: Must accept tenant context from parent system
- **Stateless**: API should remain stateless for horizontal scaling
- **Developer Experience**: Auth should not complicate local development

## Considered Options

### Option 1: JWT with RS256 + Refresh Tokens

Use asymmetric JWT tokens with RSA signing and refresh token rotation.

**Pros:**
- Stateless authentication (scalable)
- RS256 allows key rotation and verification-only public keys
- Refresh tokens enable short-lived access tokens
- Industry standard, well-understood
- Works standalone and with OpsOrchestra

**Cons:**
- Token revocation requires additional infrastructure
- JWT size larger than session IDs
- Complexity of key management

### Option 2: Session-Based Authentication

Traditional server-side sessions with cookies.

**Pros:**
- Simple to implement
- Easy to revoke sessions
- Smaller cookie size

**Cons:**
- Requires session storage (Redis)
- Not stateless, harder to scale
- Cookie handling complex for API clients
- Not suitable for OpsOrchestra integration

### Option 3: OAuth 2.0 / OpenID Connect

Full OAuth 2.0 implementation with OIDC for identity.

**Pros:**
- Industry standard
- Supports external identity providers
- Rich ecosystem

**Cons:**
- Significant implementation complexity
- Overkill for current needs
- Requires authorization server infrastructure
- Complex for simple API clients

### Option 4: API Keys

Simple API key authentication.

**Pros:**
- Very simple to implement
- Easy for API integrations

**Cons:**
- No user identity, only client identity
- Keys don't expire (security risk)
- No refresh mechanism
- Not suitable for web UI

## Decision

**Implement Option 1: JWT with RS256 + Refresh Tokens, with RBAC.**

We will implement:
1. **JWT Access Tokens**: RS256 signed, 1-hour expiry
2. **Refresh Tokens**: Secure random tokens, 7-day expiry, rotation on use
3. **RBAC**: Role-based access control with predefined roles (viewer/editor/admin/owner)
4. **Tenant Context**: Every token carries org_id claim
5. **Token Revocation**: jti claim + denylist for compromised tokens
6. **OpsOrchestra Mode**: Accept and validate parent system tokens
7. **Development Mode**: Simplified auth for local development
8. **API Keys**: Service-to-service auth for integrations (org-scoped, hashed)

Rationale:
- RS256 allows separating signing (private key) from verification (public key)
- Short-lived access tokens limit exposure if compromised
- Refresh token rotation detects token theft
- RBAC provides flexible but manageable permissions
- org_id claim ensures isolation at token level

## Consequences

### Positive
- Secure, industry-standard authentication
- Stateless tokens enable horizontal scaling
- RBAC provides clear permission model
- Tenant isolation enforced at auth layer
- Supports both standalone and OpsOrchestra modes
- SOC2 access control requirements met

### Negative
- Key management complexity
- Token revocation requires deny-list or short expiry
- Implementation requires careful security review
- Adds latency for token validation

### Neutral
- Requires secure key storage (secrets manager)
- Training needed for RBAC configuration
- Refresh flow adds client complexity

## Implementation Notes

### Token Structure

```python
# Access Token Claims
{
    "sub": "user-123",           # User ID
    "org_id": "org-456",         # Organization context (required)
    "email": "user@example.com", # User email
    "roles": ["viewer"],         # User roles
    "permissions": ["assessment:read"],
    "iat": 1706360000,           # Issued at
    "exp": 1706363600,           # Expires (1 hour)
    "jti": "token-abc123",       # Token ID for revocation
    "iss": "scalescore",         # Issuer
    "aud": "scalescore-api",     # Audience
}
```

### Role Definitions

```python
# src/scalescore/core/auth/roles.py
from enum import Enum
from typing import Set


class Permission(str, Enum):
    """Granular permissions for RBAC."""
    # Assessments
    ASSESSMENT_CREATE = "assessment:create"
    ASSESSMENT_READ = "assessment:read"
    ASSESSMENT_DELETE = "assessment:delete"
    
    # Reports
    REPORT_VIEW = "report:view"
    REPORT_EXPORT = "report:export"
    
    # Organizations
    ORGANIZATION_MANAGE = "organization:manage"
    ORGANIZATION_DELETE = "organization:delete"
    ENTITY_MANAGE = "entity:manage"
    BILLING_MANAGE = "billing:manage"
    
    # Users (admin)
    USER_MANAGE = "user:manage"
    USER_VIEW = "user:view"
    
    # System (admin)
    SYSTEM_CONFIG = "system:config"
    AUDIT_VIEW = "audit:view"


class Role(str, Enum):
    """Predefined roles with permission sets."""
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"
    OWNER = "owner"


# Role to permissions mapping
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.VIEWER: {
        Permission.ASSESSMENT_READ,
        Permission.REPORT_VIEW,
    },
    Role.EDITOR: {
        Permission.ASSESSMENT_CREATE,
        Permission.ASSESSMENT_READ,
        Permission.REPORT_VIEW,
        Permission.REPORT_EXPORT,
        Permission.ENTITY_MANAGE,
    },
    Role.ADMIN: {
        Permission.ASSESSMENT_CREATE,
        Permission.ASSESSMENT_READ,
        Permission.ASSESSMENT_DELETE,
        Permission.REPORT_VIEW,
        Permission.REPORT_EXPORT,
        Permission.ORGANIZATION_MANAGE,
        Permission.ENTITY_MANAGE,
        Permission.USER_MANAGE,
        Permission.USER_VIEW,
        Permission.SYSTEM_CONFIG,
        Permission.AUDIT_VIEW,
    },
    Role.OWNER: set(Permission),
}


def get_permissions(roles: list[str]) -> Set[Permission]:
    """Get combined permissions for a list of roles."""
    permissions: Set[Permission] = set()
    for role_name in roles:
        try:
            role = Role(role_name)
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        except ValueError:
            continue  # Ignore invalid roles
    return permissions
```

### JWT Service

```python
# src/scalescore/core/auth/jwt.py
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel

from scalescore.config import settings
from scalescore.core.exceptions import AuthenticationError, ErrorCode


class TokenPayload(BaseModel):
    """Validated token payload."""
    sub: str  # User ID
    org_id: str
    email: str
    roles: list[str]
    jti: str
    exp: datetime
    iat: datetime


class JWTService:
    """Service for JWT token operations."""
    
    def __init__(self):
        self._private_key = self._load_private_key()
        self._public_key = self._load_public_key()
    
    def _load_private_key(self):
        """Load RSA private key for signing."""
        key_path = settings.auth.jwt_private_key_path
        if key_path:
            with open(key_path, "rb") as f:
                return serialization.load_pem_private_key(
                    f.read(),
                    password=settings.auth.jwt_key_password.get_secret_value().encode()
                    if settings.auth.jwt_key_password
                    else None,
                )
        # Generate ephemeral key for development
        if settings.is_development():
            return rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
        raise ValueError("JWT private key not configured for production")
    
    def _load_public_key(self):
        """Load RSA public key for verification."""
        key_path = settings.auth.jwt_public_key_path
        if key_path:
            with open(key_path, "rb") as f:
                return serialization.load_pem_public_key(f.read())
        # Derive from private key
        return self._private_key.public_key()
    
    def create_access_token(
        self,
        user_id: str,
        org_id: str,
        email: str,
        roles: list[str],
    ) -> str:
        """Create a signed JWT access token."""
        import uuid
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=settings.auth.access_token_expire_minutes)
        jti = str(uuid.uuid4())
        
        payload = {
            "sub": user_id,
            "org_id": org_id,
            "email": email,
            "roles": roles,
            "iat": now,
            "exp": expires,
            "jti": jti,
            "iss": "scalescore",
            "aud": "scalescore-api",
        }
        
        return jwt.encode(
            payload,
            self._private_key,
            algorithm="RS256",
        )
    
    def verify_token(self, token: str) -> TokenPayload:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                audience="scalescore-api",
                issuer="scalescore",
            )
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError:
            raise AuthenticationError(
                message="Token has expired",
                code=ErrorCode.TOKEN_EXPIRED,
            )
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(
                message="Invalid token",
                code=ErrorCode.INVALID_TOKEN,
                details={"reason": str(e)},
            )
    
    def get_public_key_jwk(self) -> dict[str, Any]:
        """Get public key in JWK format for external verification."""
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        
        public_bytes = self._public_key.public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo,
        )
        # Convert to JWK format
        # (simplified - use python-jose or similar for full JWK support)
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": "scalescore-key-1",
        }
```

### Refresh Token Service

```python
# src/scalescore/core/auth/refresh.py
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from scalescore.config import settings
from scalescore.core.exceptions import AuthenticationError, ErrorCode


class RefreshTokenService:
    """Service for refresh token operations."""
    
    def __init__(self, repository):  # Inject token repository
        self.repository = repository
        self.token_length = 64
        self.expire_days = settings.auth.refresh_token_expire_days
    
    def create_refresh_token(
        self,
        user_id: str,
        org_id: str,
        device_info: Optional[str] = None,
    ) -> str:
        """Create and store a new refresh token."""
        token = secrets.token_urlsafe(self.token_length)
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.expire_days)
        
        # Store hashed token
        token_hash = self._hash_token(token)
        self.repository.store_refresh_token(
            token_hash=token_hash,
            user_id=user_id,
            org_id=org_id,
            expires_at=expires_at,
            device_info=device_info,
        )
        
        return token
    
    def rotate_refresh_token(
        self,
        old_token: str,
        device_info: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Rotate refresh token and return new access + refresh tokens.
        
        Returns:
            Tuple of (new_access_token, new_refresh_token)
        """
        old_hash = self._hash_token(old_token)
        
        # Validate and get token data
        token_data = self.repository.get_refresh_token(old_hash)
        if not token_data:
            raise AuthenticationError(
                message="Invalid refresh token",
                code=ErrorCode.INVALID_REFRESH_TOKEN,
            )
        
        if token_data.expires_at < datetime.now(timezone.utc):
            self.repository.revoke_refresh_token(old_hash)
            raise AuthenticationError(
                message="Refresh token has expired",
                code=ErrorCode.REFRESH_TOKEN_EXPIRED,
            )
        
        # Check for token reuse (potential theft detection)
        if token_data.used:
            # Token was already used - revoke all tokens for this user
            self.repository.revoke_all_user_tokens(token_data.user_id)
            raise AuthenticationError(
                message="Token reuse detected - all sessions revoked",
                code=ErrorCode.TOKEN_REUSE_DETECTED,
            )
        
        # Mark old token as used
        self.repository.mark_token_used(old_hash)
        
        # Create new refresh token
        new_refresh_token = self.create_refresh_token(
            user_id=token_data.user_id,
            org_id=token_data.org_id,
            device_info=device_info,
        )
        
        # Create new access token
        jwt_service = JWTService()
        user = self.repository.get_user(token_data.user_id)
        new_access_token = jwt_service.create_access_token(
            user_id=user.id,
            org_id=user.org_id,
            email=user.email,
            roles=user.roles,
        )
        
        return new_access_token, new_refresh_token
    
    def _hash_token(self, token: str) -> str:
        """Hash token for storage."""
        import hashlib
        return hashlib.sha256(token.encode()).hexdigest()
```

### FastAPI Dependencies

```python
# src/scalescore/api/dependencies/auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from scalescore.core.auth.jwt import JWTService, TokenPayload
from scalescore.core.auth.roles import Permission, get_permissions
from scalescore.core.exceptions import AuthenticationError

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    """Validate access token and return user payload."""
    jwt_service = JWTService()
    try:
        return jwt_service.verify_token(credentials.credentials)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.to_dict(),
            headers={"WWW-Authenticate": "Bearer"},
        )


class RequirePermission:
    """Dependency to check for specific permission."""
    
    def __init__(self, permission: Permission):
        self.permission = permission
    
    async def __call__(
        self,
        current_user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        user_permissions = get_permissions(current_user.roles)
        if self.permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_PERMISSIONS",
                    "message": f"Missing required permission: {self.permission.value}",
                },
            )
        return current_user


def get_org_id(
    current_user: TokenPayload = Depends(get_current_user),
) -> str:
    """Extract org_id from current user."""
    return current_user.org_id
```

### Usage in Endpoints

```python
# src/scalescore/api/v1/assessments.py
from fastapi import APIRouter, Depends

from scalescore.api.dependencies.auth import (
    get_current_user,
    get_org_id,
    RequirePermission,
)
from scalescore.core.auth.roles import Permission
from scalescore.core.auth.jwt import TokenPayload

router = APIRouter()


@router.post("/assessments")
async def create_assessment(
    request: AssessmentRequest,
    current_user: TokenPayload = Depends(
        RequirePermission(Permission.ASSESSMENT_CREATE)
    ),
    org_id: str = Depends(get_org_id),
) -> ScaleScoreReport:
    """Create a new assessment (requires assessment:create permission)."""
    return await run_assessment(request, org_id=org_id)


@router.get("/assessments/{assessment_id}")
async def get_assessment(
    assessment_id: str,
    current_user: TokenPayload = Depends(
        RequirePermission(Permission.ASSESSMENT_READ)
    ),
    org_id: str = Depends(get_org_id),
) -> ScaleScoreReport:
    """Get assessment by ID (requires assessment:read permission)."""
    return await get_assessment_by_id(assessment_id, org_id=org_id)
```

### Development Mode

```python
# src/scalescore/api/dependencies/auth.py (addition)
from scalescore.config import settings


async def get_current_user_dev() -> TokenPayload:
    """Development-only: Return mock user."""
    return TokenPayload(
        sub="dev-user-1",
        org_id="org-dev",
        email="dev@localhost",
        roles=["admin"],
        jti="dev-token",
        exp=datetime.max,
        iat=datetime.now(timezone.utc),
    )


# Use development dependency if in dev mode
if settings.is_development() and settings.auth.skip_auth:
    get_current_user = get_current_user_dev
```

### OpsOrchestra Integration Mode

```python
# src/scalescore/core/auth/opsorchestra.py
from scalescore.core.auth.jwt import TokenPayload
from scalescore.config import settings


class OpsOrchestraAuthService:
    """Validate tokens from OpsOrchestra parent system."""
    
    def __init__(self):
        self.public_key = self._load_opsorchestra_public_key()
    
    def _load_opsorchestra_public_key(self):
        """Load OpsOrchestra's public key for token verification."""
        key_url = settings.opsorchestra.public_key_url
        # Fetch and cache public key
        # ...
    
    def verify_parent_token(self, token: str) -> TokenPayload:
        """Verify token issued by OpsOrchestra."""
        # Verify with OpsOrchestra's public key
        # Map OpsOrchestra claims to ScaleScore claims
        # ...
```

### Auth Endpoints

```python
# src/scalescore/api/v1/auth.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest) -> TokenResponse:
    """Authenticate and return tokens."""
    # Validate credentials
    user = await authenticate_user(request.email, request.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
        )
    
    # Create tokens
    jwt_service = JWTService()
    refresh_service = RefreshTokenService(token_repository)
    
    access_token = jwt_service.create_access_token(
        user_id=user.id,
        org_id=user.org_id,
        email=user.email,
        roles=user.roles,
    )
    refresh_token = refresh_service.create_refresh_token(
        user_id=user.id,
        org_id=user.org_id,
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.auth.access_token_expire_minutes * 60,
    )


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh_tokens(refresh_token: str) -> TokenResponse:
    """Exchange refresh token for new tokens."""
    refresh_service = RefreshTokenService(token_repository)
    access_token, new_refresh_token = refresh_service.rotate_refresh_token(
        refresh_token
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.auth.access_token_expire_minutes * 60,
    )


@router.post("/auth/logout")
async def logout(
    current_user: TokenPayload = Depends(get_current_user),
    refresh_token: str = None,
):
    """Revoke refresh token."""
    if refresh_token:
        refresh_service = RefreshTokenService(token_repository)
        refresh_service.revoke_token(refresh_token)
    return {"message": "Logged out successfully"}
```

## Related Decisions

- ADR-0005: Multi-Tenancy Strategy (tenant isolation enforcement)
- ADR-0007: Error Handling Strategy (auth error codes)
- ADR-0009: Configuration Management (auth configuration)
- ADR-0010: Structured Logging and Observability (audit logging)
- ADR-0016: User Management Strategy (roles, org_id claim, revocation)

## Notes

- Store RSA keys in secrets manager (AWS Secrets Manager, HashiCorp Vault)
- Implement key rotation strategy (recommend annual rotation)
- Consider adding MFA for admin users in Phase 3
- Add rate limiting to login endpoint to prevent brute force
- Implement account lockout after failed attempts
