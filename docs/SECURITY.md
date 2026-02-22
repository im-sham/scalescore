# ScaleScore Security Architecture

> **Last Updated**: February 22, 2026  
> **Status**: Living Document  
> **Owner**: Engineering / Security  
> **Classification**: Internal

---

## Table of Contents

1. [Security Philosophy](#1-security-philosophy)
2. [Data Classification](#2-data-classification)
3. [Authentication & Authorization](#3-authentication--authorization)
4. [Data Protection](#4-data-protection)
5. [API Security](#5-api-security)
6. [Infrastructure Security](#6-infrastructure-security)
7. [Audit & Compliance](#7-audit--compliance)
8. [Incident Response](#8-incident-response)
9. [SOC2 Alignment](#9-soc2-alignment)
10. [Security Checklist](#10-security-checklist)

---

## 1. Security Philosophy

### Core Principle: Security by Design

Security is not a feature to be added later. It is a foundational property of how we build ScaleScore.

**Guiding Tenets:**

| Tenet | Description | Implementation |
|-------|-------------|----------------|
| **Assume Breach** | Design systems expecting attackers are already inside | Defense in depth, minimal blast radius |
| **Least Privilege** | Grant minimum permissions necessary | Role-based access, scoped tokens |
| **Defense in Depth** | Multiple security layers | Auth + validation + encryption + logging |
| **Secure by Default** | Safe configuration out of the box | Secure defaults, explicit opt-out |
| **Trust but Verify** | Validate all inputs regardless of source | Schema validation, sanitization |

### Security Responsibilities

| Role | Responsibilities |
|------|-----------------|
| **All Engineers** | Follow secure coding practices, raise security concerns |
| **Code Reviewers** | Verify security checklist, identify vulnerabilities |
| **Security Lead** | Architecture review, threat modeling, incident response |
| **Operations** | Infrastructure security, monitoring, patching |

---

## 2. Data Classification

All data handled by ScaleScore is classified into sensitivity levels that determine handling requirements.

### Classification Levels

| Level | Label | Description | Examples |
|-------|-------|-------------|----------|
| **L1** | Public | No sensitivity, can be exposed | Entity types, enum values |
| **L2** | Internal | Business-sensitive, tenant-isolated | Scores, recommendations, entity names |
| **L3** | Confidential | Highly sensitive, regulatory concern | Revenue, headcount, financial projections |
| **L4** | Restricted | Critical secrets, never stored | API keys, passwords, encryption keys |

### Handling Requirements by Level

| Requirement | L1 Public | L2 Internal | L3 Confidential | L4 Restricted |
|-------------|-----------|-------------|-----------------|---------------|
| Encryption in transit | Required | Required | Required | Required |
| Encryption at rest | Optional | Required | Required | N/A (not stored) |
| Tenant isolation | N/A | Required | Required | N/A |
| Audit logging | Optional | Required | Required | Required |
| Log masking | No | No | Yes | Yes |
| Access control | None | Role-based | Need-to-know | System-only |
| Backup encryption | Optional | Required | Required | N/A |
| Retention limit | None | 7 years | 3 years | Never persist |

### Data Classification in Code

```python
from enum import Enum
from pydantic import BaseModel, Field

class DataClassification(str, Enum):
    PUBLIC = "public"          # L1
    INTERNAL = "internal"      # L2
    CONFIDENTIAL = "confidential"  # L3
    RESTRICTED = "restricted"  # L4

class Organization(BaseModel):
    # L2 - Internal: tenant-isolated, not sensitive
    id: str
    name: str = Field(..., json_schema_extra={"classification": "internal"})
    
    # L3 - Confidential: mask in logs, encrypt at rest
    headcount_current: int = Field(
        ..., 
        json_schema_extra={"classification": "confidential"}
    )
    revenue_current: float = Field(
        ..., 
        json_schema_extra={"classification": "confidential"}
    )
    burn_rate_monthly: float = Field(
        ..., 
        json_schema_extra={"classification": "confidential"}
    )
```

### Classified Fields Inventory

| Model | Field | Classification | Rationale |
|-------|-------|----------------|-----------|
| Organization | revenue_current | Confidential | Financial data |
| Organization | headcount_current | Confidential | Competitive data |
| Organization | burn_rate_monthly | Confidential | Financial data |
| Organization | runway_months | Confidential | Financial data |
| Team | headcount_current | Confidential | Org structure |
| Vendor | annual_cost | Confidential | Contract terms |
| Facility | monthly_rent | Confidential | Contract terms |
| GrowthSignal | magnitude | Confidential | Strategic plans |
| ReadinessScore | score | Internal | Assessment output |
| RiskIndicator | * | Internal | Assessment output |

---

## 3. Authentication & Authorization

### Authentication Strategy

**Current (v0.3):** JWT-based auth foundation is implemented for API access  
**Platform (v0.4+):** Durable user/session persistence and broader endpoint coverage  
**Enterprise (v1.0):** JWT + SSO/SAML

### JWT Implementation

```python
# Token structure
{
    "sub": "user_id",           # User identifier
    "tenant_id": "tenant_123",  # Tenant context for access scope
    "email": "user@example.com",
    "roles": ["analyst"],
    "iat": 1706360400,          # Issued at
    "exp": 1706364000,          # Expiration (1 hour)
    "iss": "scalescore",
    "aud": "scalescore-api",
}
```

**Token Security:**
- RS256 access tokens
- 30-minute access token expiration (configurable)
- 7-day refresh token expiration (configurable)
- Refresh token rotation on use
- Refresh token persistence via hashed SQLite storage (tenant-scoped)
- Dev-only fallback credentials for local workflows

### Authorization Model

**Role-Based Access Control (RBAC):**

| Role | Permissions |
|------|-------------|
| **Viewer** | Read assessments, view scores |
| **Analyst** | All Viewer + create assessments, export reports |
| **Admin** | All Analyst + manage users and org settings |
| **Super Admin** | All permissions |

**Permission Enforcement:**

```python
from functools import wraps
from fastapi import Depends, HTTPException

def require_permission(permission: str):
    """Decorator to enforce permission checks."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user: User = Depends(get_current_user), **kwargs):
            if not current_user.has_permission(permission):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator

@router.post("/assessments/upload")
@require_permission("assessment:create")
async def create_assessment(
    files: UploadRequest,
    current_user: User = Depends(get_current_user),
) -> ScaleScoreReport:
    ...
```

### Multi-Tenancy Enforcement

**Every database query is tenant-scoped:**

```python
class OrgRepository:
    def __init__(self, session: AsyncSession, org_id: str) -> None:
        self._session = session
        self._org_id = org_id

    async def get(self, id: str) -> Entity | None:
        # Tenant isolation is ALWAYS applied
        query = select(EntityModel).where(
            EntityModel.id == id,
            EntityModel.org_id == self._org_id  # REQUIRED
        )
        return await self._session.execute(query)
```

**Tenant Context Flow:**

```
Request → Bearer token verification → Extract tenant_id from JWT →
  → Permission guard evaluates role mapping →
    → Repository enforces tenant-scoped lookups
```

---

## 4. Data Protection

### Encryption

**In Transit:**
- TLS 1.3 minimum for all connections
- HTTPS enforced (HTTP redirects to HTTPS)
- Certificate pinning for mobile clients (future)

**At Rest:**
- Database: PostgreSQL with encryption (AES-256)
- File storage: Encrypted S3 buckets (SSE-S3 or SSE-KMS)
- Backups: Encrypted with separate key

**Application-Level Encryption:**
```python
# Confidential fields encrypted before storage (future enhancement)
from cryptography.fernet import Fernet

class EncryptedField:
    def __init__(self, key: bytes):
        self._fernet = Fernet(key)
    
    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()
    
    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()
```

### Secret Management

**Principles:**
- No secrets in source code (NEVER)
- No secrets in logs (masked automatically)
- Secrets injected via environment or secrets manager
- Secrets rotated regularly

**Implementation:**

| Environment | Secret Source |
|-------------|---------------|
| Development | `.env` file (gitignored) |
| CI/CD | GitHub Secrets / GitLab CI Variables |
| Production | AWS Secrets Manager / HashiCorp Vault |

**Required Secrets:**

| Secret | Purpose | Rotation |
|--------|---------|----------|
| `DATABASE_URL` | Database connection | On compromise |
| `JWT_PRIVATE_KEY` | Token signing | 90 days |
| `JWT_PUBLIC_KEY` | Token verification | With private key |
| `ENCRYPTION_KEY` | Field encryption | 365 days |

### Data Masking

**Log Sanitization:**

```python
import re
from typing import Any

SENSITIVE_PATTERNS = {
    r'"revenue[_\w]*":\s*[\d.]+': '"revenue_***": "***"',
    r'"headcount[_\w]*":\s*\d+': '"headcount_***": "***"',
    r'"burn_rate[_\w]*":\s*[\d.]+': '"burn_rate_***": "***"',
    r'"api_key":\s*"[^"]*"': '"api_key": "***"',
}

def sanitize_log(message: str) -> str:
    """Remove sensitive data from log messages."""
    for pattern, replacement in SENSITIVE_PATTERNS.items():
        message = re.sub(pattern, replacement, message)
    return message
```

### Data Retention

| Data Type | Retention Period | Deletion Method |
|-----------|------------------|-----------------|
| Assessment reports | 7 years (default) | Soft delete → hard delete after 30 days |
| Entity data | While organization active | Soft delete on org deletion |
| Audit logs | 7 years | No deletion (compliance) |
| Session data | 30 days | Automatic expiration |
| Temporary files | 24 hours | Automatic cleanup |

---

## 5. API Security

### Input Validation

**All API inputs validated with Pydantic:**

```python
from pydantic import BaseModel, Field, validator

class CreateAssessmentRequest(BaseModel):
    org_id: str = Field(..., min_length=1, max_length=100)
    
    @validator("org_id")
    def validate_org_id(cls, v: str) -> str:
        # Whitelist allowed characters
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Invalid organization ID format")
        return v
```

### Rate Limiting

Current application-layer controls:

| Endpoint Category | Configurable Settings | Default |
|-------------------|-----------------------|---------|
| Login | `AUTH_LOGIN_RATE_LIMIT_REQUESTS`, `AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `120` / `60s` |
| Signup | `AUTH_SIGNUP_RATE_LIMIT_REQUESTS`, `AUTH_SIGNUP_RATE_LIMIT_WINDOW_SECONDS` | `30` / `3600s` |
| Refresh | `AUTH_REFRESH_RATE_LIMIT_REQUESTS`, `AUTH_REFRESH_RATE_LIMIT_WINDOW_SECONDS` | `120` / `60s` |
| Async assessment submit | `ASYNC_ASSESSMENT_SUBMIT_RATE_LIMIT_REQUESTS`, `ASYNC_ASSESSMENT_SUBMIT_RATE_LIMIT_WINDOW_SECONDS` | `60` / `60s` |

Notes:
- Controls are enforced at the API layer and return `429` with `Retry-After` when applicable.
- Async uploads also enforce tenant queue caps and per-file max upload size.
- Edge controls (WAF/CDN) are still required for broader protection.
- OWASP API Top 10 audit evidence is documented in `docs/SECURITY_OWASP_API_TOP10_AUDIT.md`.

**Implementation excerpt:**
```python
decision = rate_limiter.allow(
    key=key,
    limit=settings.auth.login_rate_limit_requests,
    window_seconds=settings.auth.login_rate_limit_window_seconds,
)
if not decision.allowed:
    raise HTTPException(status_code=429, headers={"Retry-After": str(decision.retry_after_seconds)})
```

### Security Headers

```python
from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

app = FastAPI()

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response
```

### CORS Policy

```python
from fastapi.middleware.cors import CORSMiddleware

# Production: Specific origins only
ALLOWED_ORIGINS = [
    "https://app.scalescore.io",
    "https://admin.scalescore.io",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # Never use ["*"] in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

## 6. Infrastructure Security

### Network Security

```
┌─────────────────────────────────────────────────────────────────┐
│                         INTERNET                                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                    ┌───────┴───────┐
                    │   WAF / CDN   │  ← DDoS protection, rate limiting
                    └───────┬───────┘
                            │
                    ┌───────┴───────┐
                    │ Load Balancer │  ← TLS termination
                    └───────┬───────┘
                            │
           ┌────────────────┼────────────────┐
           │                │                │
    ┌──────┴──────┐  ┌──────┴──────┐  ┌──────┴──────┐
    │   API Pod   │  │   API Pod   │  │   API Pod   │
    └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
           │                │                │
           └────────────────┼────────────────┘
                            │
                    ┌───────┴───────┐
                    │ Private Subnet│
                    │               │
                    │  ┌─────────┐  │
                    │  │ Database│  │  ← No public access
                    │  └─────────┘  │
                    │               │
                    └───────────────┘
```

### Container Security

- Base images from trusted sources only
- Regular image scanning for vulnerabilities
- Non-root user in containers
- Read-only file systems where possible
- Resource limits enforced

```dockerfile
# Example secure Dockerfile patterns
FROM python:3.11-slim

# Run as non-root user
RUN useradd -m -s /bin/bash appuser
USER appuser

# Read-only where possible
VOLUME ["/tmp"]
```

### Dependency Security

```bash
# Regular dependency audits
pip-audit                    # Python dependencies
safety check                 # Alternative scanner

# Lock dependencies
pip freeze > requirements.lock
```

**Dependency Policy:**
- Review all new dependencies for security
- Pin major versions in production
- Automated weekly dependency scans
- Critical vulnerabilities patched within 24 hours

---

## 7. Audit & Compliance

### Audit Logging

**All state-changing operations produce audit records:**

```python
from datetime import datetime
from pydantic import BaseModel

class AuditEvent(BaseModel):
    event_id: str
    timestamp: datetime
    actor_id: str           # User who performed action
    actor_ip: str           # Source IP
    org_id: str             # Organization context
    action: str             # create, update, delete, access
    resource_type: str      # assessment, organization, user
    resource_id: str        # ID of affected resource
    changes: dict | None    # Before/after for updates
    status: str             # success, failure
    correlation_id: str     # Request trace ID

# Example audit log
{
    "event_id": "evt_abc123",
    "timestamp": "2026-01-15T10:30:00Z",
    "actor_id": "user_456",
    "actor_ip": "192.168.1.100",
    "org_id": "org_acme",
    "action": "create",
    "resource_type": "assessment",
    "resource_id": "rpt_789",
    "changes": null,
    "status": "success",
    "correlation_id": "req_xyz789"
}
```

**Audit Log Requirements:**
- Append-only (no updates or deletions)
- Tamper-evident (hash chain or similar)
- Retained for 7 years minimum
- Exportable for compliance audits

### Access Logging

```python
# Request logging (sanitized)
{
    "timestamp": "2026-01-15T10:30:00Z",
    "correlation_id": "req_xyz789",
    "method": "POST",
    "path": "/api/v1/assessments",
    "status_code": 200,
    "duration_ms": 1234,
    "user_id": "user_456",
    "org_id": "org_acme",
    "ip": "192.168.1.100",
    "user_agent": "Mozilla/5.0..."
}
```

---

## 8. Incident Response

### Severity Levels

| Level | Definition | Response Time | Examples |
|-------|------------|---------------|----------|
| **SEV1** | Active security breach | 15 minutes | Data exfiltration, unauthorized access |
| **SEV2** | High-risk vulnerability | 4 hours | Critical CVE, exposed secrets |
| **SEV3** | Security concern | 24 hours | Medium CVE, access anomaly |
| **SEV4** | Low-risk issue | 1 week | Minor CVE, policy violation |

### Response Procedure

1. **Detect** - Identify potential security incident
2. **Contain** - Limit blast radius (revoke access, isolate systems)
3. **Investigate** - Determine scope and root cause
4. **Remediate** - Fix vulnerability, patch systems
5. **Recover** - Restore normal operations
6. **Review** - Post-incident analysis, update procedures

### Contact Information

| Role | Contact | Escalation |
|------|---------|------------|
| Security Lead | security@scalescore.io | Immediately for SEV1/2 |
| Engineering Lead | engineering@scalescore.io | For technical response |
| Legal/Compliance | legal@scalescore.io | For breach notification |

---

## 9. SOC2 Alignment

ScaleScore is designed with SOC2 Type II certification as a target. This section maps our controls to SOC2 Trust Service Criteria.

### Trust Service Criteria Mapping

#### CC1: Control Environment

| Control | Implementation |
|---------|----------------|
| CC1.1 Board oversight | Quarterly security reviews |
| CC1.2 Management commitment | Security-first engineering culture |
| CC1.3 Organizational structure | Defined security responsibilities |
| CC1.4 Competence | Security training for all engineers |

#### CC2: Communication and Information

| Control | Implementation |
|---------|----------------|
| CC2.1 Internal communication | Security documentation, training |
| CC2.2 External communication | Privacy policy, security page |
| CC2.3 Security information | Audit logs, monitoring |

#### CC3: Risk Assessment

| Control | Implementation |
|---------|----------------|
| CC3.1 Risk objectives | Threat modeling per feature |
| CC3.2 Risk identification | Regular security assessments |
| CC3.3 Fraud consideration | Input validation, audit trails |
| CC3.4 Change analysis | Security review for architecture changes |

#### CC5: Control Activities

| Control | Implementation |
|---------|----------------|
| CC5.1 Control selection | Defense in depth approach |
| CC5.2 Technology controls | Authentication, encryption, logging |
| CC5.3 Policies and procedures | This document + CONTRIBUTING.md |

#### CC6: Logical and Physical Access

| Control | Implementation |
|---------|----------------|
| CC6.1 Logical access | JWT authentication, RBAC |
| CC6.2 Authentication | Multi-factor (planned), secure tokens |
| CC6.3 Access authorization | Role-based, need-to-know |
| CC6.4 Access review | Quarterly access audits |
| CC6.5 Access removal | Immediate revocation on termination |
| CC6.6 Infrastructure access | Limited, audited, MFA required |

#### CC7: System Operations

| Control | Implementation |
|---------|----------------|
| CC7.1 Vulnerability management | Dependency scanning, patching |
| CC7.2 Change management | PR review, staging deployment |
| CC7.3 System monitoring | Logging, alerting, metrics |

#### CC8: Change Management

| Control | Implementation |
|---------|----------------|
| CC8.1 Change authorization | PR approval required |
| CC8.2 Change testing | CI/CD with security tests |
| CC8.3 Configuration management | Infrastructure as code |

#### CC9: Risk Mitigation

| Control | Implementation |
|---------|----------------|
| CC9.1 Vendor management | Security review for vendors |
| CC9.2 Contract compliance | Security requirements in contracts |

### Confidentiality Criteria

| Control | Implementation |
|---------|----------------|
| C1.1 Confidentiality policies | Data classification scheme |
| C1.2 Confidentiality commitments | Privacy policy, contracts |

### Availability Criteria

| Control | Implementation |
|---------|----------------|
| A1.1 Capacity planning | Scalability design |
| A1.2 Environmental protections | Cloud provider SLA |
| A1.3 Backup and recovery | Daily backups, tested recovery |

---

## 10. Security Checklist

### Pre-Commit Security Checks

- [ ] No secrets in code (use pre-commit hook)
- [ ] Sensitive data classified and handled appropriately
- [ ] All inputs validated with Pydantic
- [ ] Tenant isolation maintained in queries
- [ ] Error messages don't leak sensitive info
- [ ] Audit logging for state changes

### Pre-Merge Security Review

- [ ] No new dependencies without security review
- [ ] Authentication/authorization enforced
- [ ] SQL injection protected (parameterized queries)
- [ ] XSS protected (output encoding)
- [ ] CSRF protected (token validation)
- [ ] Rate limiting considered

### Pre-Deploy Security Validation

- [ ] Dependency vulnerability scan clean
- [ ] Security tests passing
- [ ] Configuration review (no debug mode)
- [ ] Secrets in secrets manager (not env files)
- [ ] TLS certificate valid

### Regular Security Activities

| Activity | Frequency |
|----------|-----------|
| Dependency vulnerability scan | Weekly (automated) |
| Access review | Quarterly |
| Security training | Annually |
| Penetration testing | Annually (or major release) |
| Backup recovery test | Quarterly |
| Incident response drill | Annually |

---

## Appendix A: Security Contacts

| Role | Email | Responsibility |
|------|-------|----------------|
| Security Lead | security@scalescore.io | Overall security program |
| Responsible Disclosure | security@scalescore.io | Vulnerability reports |

## Appendix B: Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Jan 2026 | Engineering | Initial document |
