# ADR-0016: User Management Strategy

**Status**: Proposed  
**Date**: 2026-02-03  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ADR-0011 established JWT-based authentication with RBAC. However, it left several user management decisions unresolved:

- Where do users live in the database?
- How are passwords stored securely?
- Can users belong to multiple organizations?
- How are users provisioned (created)?

These decisions are prerequisites for implementing the auth system end-to-end. They also affect:

- Multi-tenancy isolation (ADR-0005)
- Database schema design (ADR-0006)
- OpsOrchestra integration mode
- SOC2 compliance posture

This ADR also aligns with:

- docs/TECHNICAL_SPEC.md
- docs/SECURITY.md
- docs/ARCHITECTURE.md
- docs/ROADMAP.md

## Decision Drivers

- **Security**: Password storage must follow OWASP best practices
- **Multi-tenancy**: Must support tenant isolation per ADR-0005
- **Flexibility**: Users may need access to multiple organizations (consultants, MSPs)
- **Enterprise-ready**: Path to SSO/SCIM for enterprise customers
- **Simplicity**: Minimize complexity for MVP while enabling future growth
- **Consistency**: Align with existing ADRs (shared DB, RLS, repository pattern)

## Decisions

This ADR covers seven related decisions:

1. Password hashing algorithm
2. User data storage location
3. User-tenant membership model
4. Token claims, expiry, and revocation alignment
5. User provisioning strategy
6. Service-to-service authentication (API keys)
7. Audit logging and data classification requirements

---

## Decision 1: Password Hashing Algorithm

### Considered Options

| Algorithm | OWASP Ranking | Memory-Hard | Python Support | Notes |
|-----------|---------------|-------------|----------------|-------|
| **Argon2id** | #1 Primary | Yes | argon2-cffi | Winner of 2015 PHC |
| scrypt | #2 Fallback | Yes | hashlib | Good, but Argon2 preferred |
| bcrypt | #3 Legacy | No | bcrypt | 72-byte limit, legacy only |
| PBKDF2 | #4 FIPS | No | hashlib | Only if FIPS-140 required |

### Decision

**Use Argon2id** with OWASP-recommended parameters:

| Parameter | Value | Description |
|-----------|-------|-------------|
| Memory (m) | 19456 (19 MiB) | RAM required per hash |
| Iterations (t) | 2 | Time cost |
| Parallelism (p) | 1 | Thread count |

### Rationale

- OWASP explicitly recommends Argon2id as primary choice
- Memory-hardness resists GPU/ASIC attacks better than bcrypt
- No input length limits (bcrypt has 72-byte limit)
- `argon2-cffi` package is well-maintained with secure defaults
- Can tune parameters as hardware improves

### Implementation

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(password: str, hash: str) -> bool:
    try:
        ph.verify(hash, password)
        return True
    except VerifyMismatchError:
        return False

def needs_rehash(hash: str) -> bool:
    return ph.check_needs_rehash(hash)
```

---

## Decision 2: User Data Storage Location

### Considered Options

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **Shared database** | Users in same PostgreSQL as app data | Simple transactions, consistent with ADR-0005/0006 | Single point of failure |
| Separate auth database | Dedicated database for auth | Stronger isolation | Distributed transactions, operational overhead |
| External IdP only | Delegate to Auth0/Clerk/WorkOS | No user storage burden | Vendor lock-in, cost, less control |

### Decision

**Store users in shared PostgreSQL database**, consistent with ADR-0005 and ADR-0006.

### Rationale

- ADR-0005 chose shared database with discriminator column
- ADR-0006 chose PostgreSQL with RLS
- User creation + organization membership should be atomic (single transaction)
- Separate auth DB adds complexity without proportional benefit at our scale
- Can migrate to separate DB later if compliance requires it

### Schema Location

```
scalescore database
├── organizations (org_id is tenant context in MVP)
├── users (NO org_id - global identity)
├── memberships (links users to organizations)
├── refresh_tokens (session management)
├── audit_logs (org_id on all rows)
└── ... other app tables (org_id on all rows)
```

---

## Decision 3: User-Tenant Membership Model

### Considered Options

| Model | Description | Use Case |
|-------|-------------|----------|
| **Single-tenant** | `users.org_id` column | Simple B2C apps |
| **Multi-tenant membership** | Separate `memberships` table | B2B SaaS with consultants, agencies, MSPs |

### Decision

**Users can belong to multiple organizations** via a memberships join table, and roles are scoped to each organization.

**Canonical role set (from docs/SECURITY.md):**

- viewer
- editor
- admin
- owner

### Rationale

- B2B SaaS standard in 2024 (separates identity from tenancy)
- Supports real-world scenarios:
  - Consultants advising multiple clients
  - MSPs managing multiple customer orgs
  - Company acquisitions/mergers
  - OpsOrchestra integration (ADR-0005 mentions separate tenant concept)
- User identity exists once; roles are scoped to organization
- Switching organizations = new JWT with different tenant context

### Schema

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    email_verified BOOLEAN DEFAULT FALSE,
    password_hash VARCHAR(255),
    display_name VARCHAR(255),
    avatar_url VARCHAR(500),
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    invited_by UUID REFERENCES users(id),
    invited_at TIMESTAMPTZ,
    joined_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, organization_id)
);

CREATE INDEX idx_memberships_user ON memberships(user_id);
CREATE INDEX idx_memberships_org ON memberships(organization_id);
CREATE INDEX idx_memberships_status ON memberships(status);

CREATE TYPE membership_status AS ENUM ('invited', 'active', 'suspended', 'removed');
```

### Session Context

JWT carries current organization context using `org_id`:

```python
{
    "sub": "user-123",
    "org_id": "org-456",
    "email": "user@example.com",
    "roles": ["editor"],
    "jti": "token-abc123",
    "memberships": [
        {"org_id": "org-456", "role": "editor"},
        {"org_id": "org-789", "role": "viewer"}
    ]
}
```

Organization switching:
1. User calls `POST /api/v1/auth/switch-org` with target org_id
2. Backend verifies user has active membership in target org
3. New access token issued with updated org_id context
4. Refresh token remains valid (user identity unchanged)

---

## Decision 4: Token Claims, Expiry, and Revocation Alignment

### Decision

Token claims and TTL align with docs/SECURITY.md:

- `org_id` is the canonical tenant context claim (MVP uses org_id as tenant identifier)
- `jti` is required for revocation tracking
- Access token expiry: 1 hour
- Refresh token expiry: 7 days
- Revocation list (denylist) required for compromised tokens

### Rationale

- Ensures consistency with existing security architecture
- Enables token revocation without shortening access token TTL to extreme values
- Keeps integrated mode compatible with OpsOrchestra tenant context

---

---

## Decision 5: User Provisioning Strategy

### Considered Options

| Method | Description | Target Segment | Complexity |
|--------|-------------|----------------|------------|
| Self-signup | Public registration form | Consumer/B2C | Low |
| **Admin-invite** | Org admin invites users via email | SMB/Mid-market | Medium |
| SSO (SAML/OIDC) | Enterprise IdP integration | Enterprise | High |
| SCIM | Automated user lifecycle | Large Enterprise | Very High |

### Decision

**Phased implementation:**

| Phase | Method | Timeline | Prerequisite |
|-------|--------|----------|--------------|
| **Phase 1** | Admin-invite only | MVP | This ADR |
| **Phase 2** | SSO (SAML 2.0, OIDC) | Post-MVP | Enterprise demand |
| **Phase 3** | SCIM provisioning | Enterprise tier | SSO implemented |

**No self-signup** - B2B SaaS users are invited by organization admins, not random visitors.

### Rationale

- Admin-invite is the B2B standard (Slack, Notion, Linear all use this)
- Self-signup creates orphan users without organization context
- SSO is table-stakes for enterprise deals (defer until needed)
- SCIM is nice-to-have for large enterprise (automates onboarding/offboarding)
- Phased approach minimizes upfront complexity

### Phase 1 Implementation (Admin-Invite)

```python
class InviteUserRequest(BaseModel):
    email: EmailStr
    role: str = "viewer"

@router.post("/users/invite")
async def invite_user(
    request: InviteUserRequest,
    current_user: TokenPayload = Depends(RequirePermission(Permission.USER_MANAGE)),
    org_id: str = Depends(get_org_id),
) -> InviteResponse:
    existing_user = await user_repo.get_by_email(request.email)
    
    if existing_user:
        existing_membership = await membership_repo.get(
            user_id=existing_user.id, 
            organization_id=org_id
        )
        if existing_membership:
            raise ConflictError("User already member of this organization")
        
        membership = await membership_repo.create(
            user_id=existing_user.id,
            organization_id=org_id,
            role=request.role,
            status="active",
            invited_by=current_user.sub,
        )
        return InviteResponse(status="added", user_id=existing_user.id)
    
    invite_token = secrets.token_urlsafe(32)
    await invite_repo.create(
        email=request.email,
        organization_id=org_id,
        role=request.role,
        invited_by=current_user.sub,
        token=invite_token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    
    await email_service.send_invite(
        to=request.email,
        invite_url=f"{settings.app_url}/invite/{invite_token}",
        organization_name=current_org.name,
        inviter_name=current_user.email,
    )
    
    return InviteResponse(status="invited", expires_in_days=7)
```

### Invite Acceptance Flow

```
1. Admin sends invite → InviteRecord created with token
2. User receives email with invite link
3. User clicks link → Frontend shows registration form
4. User sets password → User + Membership created atomically
5. User redirected to dashboard in organization context

---

## Decision 6: Service-to-Service Authentication (API Keys)

### Decision

Support API keys for non-user integrations as a parallel auth path (docs/ROADMAP.md v0.4). API keys are tenant-scoped and do not represent a human user.

### Requirements

- Store only hashed API keys (never plaintext)
- Keys scoped to `org_id` and bound to roles or explicit permissions
- Key rotation supported; old keys can be revoked
- API key access is read/write only for allowed endpoints

---

## Decision 7: Audit Logging and Data Classification

### Audit Logging Requirements

All state-changing user operations MUST emit audit events (docs/SECURITY.md):

- user.invite
- user.invite.accepted
- user.created
- user.updated
- user.disabled
- membership.added
- membership.role.changed
- membership.removed
- auth.login.success
- auth.login.failure
- auth.logout
- auth.token.revoked

### Data Classification for User Fields

| Field | Classification | Handling |
|------|----------------|----------|
| email | Internal (L2) | Mask in logs where feasible |
| password_hash | Restricted (L4) | Store only hashed, never log |
| mfa_secret | Restricted (L4) | Encrypted at rest, never log |
| last_login_at | Internal (L2) | Audit-safe |
| is_active | Internal (L2) | Audit-safe |

---

## OpsOrchestra Integration Mode

### Decision

When integrated with OpsOrchestra, ScaleScore trusts the upstream session context and maps it into its own user model:

- Users may be provisioned as shadow records with `external_id` and no password_hash
- `org_id` in ScaleScore is mapped from OpsOrchestra tenant context
- Memberships are derived from OpsOrchestra claims and cached locally for authorization
```

---

## Consequences

### Positive

- Argon2id provides best-in-class password security
- Multi-membership enables enterprise use cases (consultants, MSPs)
- Shared database keeps operations simple
- Phased provisioning minimizes upfront complexity
- Clear path to SSO/SCIM for enterprise deals

### Negative

- Multi-membership adds schema complexity vs single-tenant
- Organization switching adds UX complexity
- No self-signup may limit viral growth (acceptable for B2B)

### Neutral

- Must implement invite flow before auth is complete
- Email service required for invitations
- Future SSO implementation will require significant work

---

## Implementation Plan

### Phase 1: Core User Management (This Sprint)

1. Add `argon2-cffi` to dependencies
2. Create User model and repository
3. Create Membership model and repository  
4. Create password service (hash, verify, needs_rehash)
5. Implement invite flow (create invite, accept invite)
6. Wire up login endpoint to real user lookup
7. Add organization switching endpoint
8. Add token revocation list support (jti denylist)
9. Add audit logging for user and auth events

### Phase 2: SSO (Future)

1. Add SAML 2.0 support (python3-saml)
2. Add OIDC support (authlib)
3. Implement JIT provisioning (create user on first SSO login)
4. Organization-level SSO configuration

### Phase 3: SCIM (Future)

1. Implement SCIM 2.0 endpoints
2. User lifecycle automation
3. Group/role sync

### Phase 4: API Keys (Parallel Track)

1. Add API key model and repository
2. Hash and store API keys securely
3. Add API key auth dependency
4. Audit log API key usage

---

## Database Migrations

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    email_verified BOOLEAN DEFAULT FALSE,
    password_hash VARCHAR(255),
    display_name VARCHAR(255),
    avatar_url VARCHAR(500),
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    invited_by UUID REFERENCES users(id),
    invited_at TIMESTAMPTZ,
    joined_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, organization_id)
);

CREATE TABLE user_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    token VARCHAR(255) UNIQUE NOT NULL,
    invited_by UUID NOT NULL REFERENCES users(id),
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key_hash VARCHAR(255) UNIQUE NOT NULL,
    key_prefix VARCHAR(12) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    created_by UUID REFERENCES users(id),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE revoked_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jti VARCHAR(64) UNIQUE NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_active ON users(is_active);
CREATE INDEX idx_memberships_user ON memberships(user_id);
CREATE INDEX idx_memberships_org ON memberships(organization_id);
CREATE INDEX idx_memberships_status ON memberships(status);
CREATE INDEX idx_invites_token ON user_invites(token);
CREATE INDEX idx_invites_email ON user_invites(email);
CREATE INDEX idx_api_keys_org ON api_keys(organization_id);
CREATE INDEX idx_api_keys_prefix ON api_keys(key_prefix);
CREATE INDEX idx_revoked_tokens_expires ON revoked_tokens(expires_at);
```

---

## Related Decisions

- ADR-0005: Multi-Tenancy Strategy (shared DB with discriminator)
- ADR-0006: PostgreSQL as Primary Database (RLS, JSONB)
- ADR-0011: Authentication and Authorization Strategy (JWT, RBAC)
- ADR-0004: Repository Pattern (user/membership repositories)

## Notes

- Consider adding pepper to Argon2id hashes (stored in secrets manager)
- Implement account lockout after N failed login attempts
- Add rate limiting to login/invite endpoints
- Consider WebAuthn/passkeys for Phase 2 (passwordless)
- Audit log all user management actions per ADR-0010
