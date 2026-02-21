# ADR-0008: API Versioning Strategy

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore exposes a REST API that will be consumed by:
- The Streamlit dashboard (internal)
- OpsOrchestra integration (external)
- Future third-party integrations

As the API evolves, we need a strategy to:
- Introduce new features without breaking existing clients
- Deprecate and remove old functionality safely
- Maintain multiple API versions during transition periods
- Communicate changes effectively to consumers

Currently, the API uses URL path versioning (`/api/v1/...`) but lacks formal policies for breaking changes, deprecation timelines, and version lifecycle management.

## Decision Drivers

- **Client Stability**: External integrations (OpsOrchestra) require predictable API contracts
- **Evolution Flexibility**: API must evolve without excessive backward compatibility burden
- **Developer Experience**: Clear versioning makes integration straightforward
- **Operational Simplicity**: Minimize complexity of maintaining multiple versions
- **Industry Standards**: Follow established patterns familiar to API consumers

## Considered Options

### Option 1: URL Path Versioning

Version embedded in URL path: `/api/v1/assessments`, `/api/v2/assessments`

**Pros:**
- Highly visible and explicit
- Easy to route and cache
- Simple to implement in FastAPI
- Easy to test different versions
- Industry standard (Stripe, GitHub, Google)

**Cons:**
- URLs change between versions
- Can lead to code duplication across versions
- Version visible in all API references

### Option 2: Header Versioning

Version specified via custom header: `X-API-Version: 1` or `Accept: application/vnd.scalescore.v1+json`

**Pros:**
- Clean URLs that don't change
- Single resource representation
- More RESTful in theory

**Cons:**
- Version hidden, easy to forget
- Harder to test (need to set headers)
- Caching more complex
- Less discoverable

### Option 3: Query Parameter Versioning

Version as query parameter: `/api/assessments?version=1`

**Pros:**
- URLs mostly stable
- Easy to switch versions in testing
- Visible but less intrusive

**Cons:**
- Pollutes query string
- Can conflict with other parameters
- Less common pattern
- Caching complications

### Option 4: No Versioning (Evolutionary)

No explicit versions; use additive changes only and content negotiation.

**Pros:**
- Simplest implementation
- Forces backward compatibility discipline
- Single codebase

**Cons:**
- Cannot make breaking changes
- Accumulates cruft over time
- Harder to remove deprecated features
- Not viable for significant API changes

## Decision

**Continue with Option 1: URL Path Versioning** with formalized policies for version lifecycle and deprecation.

We will:
1. Maintain URL path versioning (`/api/v1/`, `/api/v2/`, etc.)
2. Define what constitutes a breaking change
3. Establish a 6-month minimum deprecation window
4. Implement version lifecycle stages
5. Provide clear deprecation headers and documentation

Rationale:
- URL path versioning is already in use and well-understood
- Industry standard familiar to API consumers
- Explicit routing simplifies implementation and debugging
- OpsOrchestra and other integrations benefit from stable, explicit versions

## Consequences

### Positive
- Clear, explicit version contracts
- Easy to route requests to correct handlers
- Simple testing of version-specific behavior
- Familiar pattern for API consumers
- Clean separation of version-specific code

### Negative
- Must maintain multiple version routers when versions overlap
- URL changes require client updates on major versions
- Some code duplication between versions

### Neutral
- Requires documentation of version differences
- Deprecation timeline enforcement needed

## Implementation Notes

### Version Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│                     API Version Lifecycle                            │
├─────────────────────────────────────────────────────────────────────┤
│  PREVIEW → CURRENT → DEPRECATED → SUNSET                            │
│     │         │           │           │                              │
│  Optional   Active     6+ months   Removed                          │
│  unstable   stable     warning     completely                        │
└─────────────────────────────────────────────────────────────────────┘
```

| Stage | Duration | Behavior |
|-------|----------|----------|
| **Preview** | Variable | May change without notice, opt-in only |
| **Current** | Until next major | Fully supported, no breaking changes |
| **Deprecated** | Minimum 6 months | Works but returns deprecation headers |
| **Sunset** | - | Removed, returns 410 Gone |

### Breaking Change Definition

The following are considered **breaking changes** requiring a new major version:

- Removing an endpoint
- Removing a request/response field
- Changing a field's type
- Changing required/optional status of a field
- Changing error response structure
- Changing authentication requirements
- Changing the meaning of a field

The following are **NOT breaking changes**:

- Adding new endpoints
- Adding optional request fields
- Adding response fields
- Adding new error codes
- Adding new enum values (if clients handle unknown values)
- Performance improvements
- Bug fixes (unless clients depend on buggy behavior)

### Router Organization

```python
# src/scalescore/api/main.py
from fastapi import FastAPI
from scalescore.api.v1 import router as v1_router
from scalescore.api.v2 import router as v2_router  # Future

app = FastAPI(
    title="ScaleScore API",
    version="1.0.0",
    description="Operational Readiness Prediction System",
)

# Mount versioned routers
app.include_router(v1_router, prefix="/api/v1", tags=["v1"])
# app.include_router(v2_router, prefix="/api/v2", tags=["v2"])  # Future

# Health check (unversioned)
@app.get("/health")
async def health_check():
    return {"status": "healthy", "api_versions": ["v1"]}
```

### Version Router Structure

```python
# src/scalescore/api/v1/__init__.py
from fastapi import APIRouter
from scalescore.api.v1 import assessments, organizations, health

router = APIRouter()

router.include_router(assessments.router, prefix="/assessments", tags=["assessments"])
router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
router.include_router(health.router, prefix="/health", tags=["health"])
```

### Deprecation Headers

```python
# src/scalescore/api/middleware/deprecation.py
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime

DEPRECATED_VERSIONS = {
    "v1": {
        "deprecated_at": "2027-01-01",
        "sunset_at": "2027-07-01",
        "successor": "v2",
    },
}


class DeprecationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # Check if this is a deprecated version
        path = request.url.path
        for version, info in DEPRECATED_VERSIONS.items():
            if f"/api/{version}/" in path:
                response.headers["Deprecation"] = info["deprecated_at"]
                response.headers["Sunset"] = info["sunset_at"]
                response.headers["Link"] = (
                    f'</api/{info["successor"]}>; rel="successor-version"'
                )
        
        return response
```

### Sunset Response

```python
# src/scalescore/api/middleware/sunset.py
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime

SUNSET_VERSIONS = {"v0"}  # Fully removed versions


class SunsetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        for version in SUNSET_VERSIONS:
            if f"/api/{version}/" in path:
                return JSONResponse(
                    status_code=410,
                    content={
                        "error": {
                            "code": "API_VERSION_SUNSET",
                            "message": f"API version {version} has been removed",
                            "details": {
                                "current_version": "v1",
                                "migration_guide": "https://docs.scalescore.io/migration/v0-to-v1",
                            },
                        },
                    },
                )
        
        return await call_next(request)
```

### Version Changelog

Maintain a changelog at `/api/versions` endpoint:

```python
# src/scalescore/api/versions.py
from fastapi import APIRouter
from pydantic import BaseModel
from datetime import date

router = APIRouter()


class VersionInfo(BaseModel):
    version: str
    status: str  # preview, current, deprecated, sunset
    released: date
    deprecated: date | None = None
    sunset: date | None = None
    changelog_url: str


@router.get("/versions")
async def list_versions() -> list[VersionInfo]:
    return [
        VersionInfo(
            version="v1",
            status="current",
            released=date(2026, 1, 15),
            deprecated=None,
            sunset=None,
            changelog_url="https://docs.scalescore.io/changelog/v1",
        ),
    ]
```

### Assessment Version vs API Version

```python
# These are INDEPENDENT versioning concepts

# API Version: How the API is structured
# - Affects: endpoints, request/response shapes, authentication
# - Example: /api/v1/assessments vs /api/v2/assessments

# Assessment Version: How scoring algorithms work
# - Affects: score calculations, recommendations
# - Example: assessment_version: "1.0" vs "2.0"

# A single API version can support multiple assessment versions
@router.post("/assessments")
async def create_assessment(
    request: AssessmentRequest,
    assessment_version: str = Query(
        default="1.0",
        description="Scoring algorithm version",
        regex=r"^\d+\.\d+$",
    ),
) -> ScaleScoreReport:
    # Use specified assessment version for scoring
    pass
```

### Directory Structure

```
src/scalescore/api/
├── __init__.py
├── main.py              # FastAPI app, mounts version routers
├── versions.py          # Version info endpoint
├── middleware/
│   ├── __init__.py
│   ├── deprecation.py   # Deprecation headers
│   └── sunset.py        # Sunset responses
├── v1/
│   ├── __init__.py      # v1 router
│   ├── assessments.py
│   ├── organizations.py
│   └── schemas.py       # v1-specific schemas
└── v2/                  # Future
    ├── __init__.py
    └── ...
```

## Related Decisions

- ADR-0002: FastAPI for API Layer (router organization)
- ADR-0007: Error Handling Strategy (error response format)
- ADR-0015: Report Immutability and Versioning (assessment version)

## Notes

- Announce deprecations in release notes, API changelog, and email to registered developers
- Consider implementing API version sunset warnings in Streamlit dashboard
- OpsOrchestra integration should specify minimum supported ScaleScore API version
