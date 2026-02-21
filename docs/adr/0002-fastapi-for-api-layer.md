# ADR-0002: Use FastAPI for API Layer

**Status**: Accepted  
**Date**: 2026-01-15  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore requires an HTTP API for:
- Running assessments
- Managing organizations and entities
- Retrieving reports and scores
- WebSocket support for real-time updates (future)
- Integration with OpsOrchestra

The API framework must support:
- Async operations for I/O-bound workloads
- Request validation
- OpenAPI documentation
- Authentication middleware
- High performance

## Decision Drivers

- **Async support**: Non-blocking I/O for database and external calls
- **Developer experience**: Fast development, good documentation
- **Pydantic integration**: Leverage our model choice (ADR-0001)
- **OpenAPI**: Automatic API documentation and client generation
- **Performance**: Handle concurrent requests efficiently
- **Security**: Built-in support for auth patterns

## Considered Options

### Option 1: FastAPI

Modern async Python framework built on Starlette and Pydantic.

**Pros:**
- Native Pydantic v2 integration (request/response validation)
- Automatic OpenAPI documentation
- Async-first design
- Excellent performance (one of fastest Python frameworks)
- Growing ecosystem and community
- Dependency injection built-in

**Cons:**
- Younger than Flask/Django (since 2018)
- Fewer third-party extensions

### Option 2: Flask

Mature micro-framework with extensive ecosystem.

**Pros:**
- Very mature, well-understood
- Huge extension ecosystem
- Simple to learn

**Cons:**
- Sync by default (async requires workarounds)
- No native Pydantic integration
- Manual OpenAPI setup
- Performance limitations for async workloads

### Option 3: Django REST Framework

Full-featured framework with REST support.

**Pros:**
- Batteries included (ORM, admin, auth)
- Very mature ecosystem
- Strong conventions

**Cons:**
- Heavyweight for our needs
- Sync by default
- ORM lock-in (we want repository pattern)
- No native Pydantic integration

### Option 4: Starlette (bare)

Low-level async framework (FastAPI is built on it).

**Pros:**
- Maximum flexibility
- Very performant

**Cons:**
- More boilerplate
- No Pydantic integration
- Manual OpenAPI

## Decision

**Use FastAPI** for the ScaleScore API layer.

Rationale:
1. Native Pydantic integration maximizes value of ADR-0001
2. Async-first design supports scalable architecture
3. Automatic OpenAPI enables API-first development
4. Dependency injection supports clean service layer design
5. Performance is excellent for Python ecosystem

## Consequences

### Positive
- Zero-boilerplate request/response validation
- Interactive API docs (Swagger, ReDoc) out of the box
- Async enables efficient I/O handling
- Type hints enable IDE autocomplete and error detection

### Negative
- Team must learn FastAPI patterns (minor learning curve)
- Some Flask/Django patterns don't apply directly

### Neutral
- Requires ASGI server (uvicorn, gunicorn with uvicorn workers)
- WebSocket support built-in but requires planning

## Implementation Notes

```python
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="ScaleScore API",
    version="0.1.0",
    description="Operational Readiness Prediction System"
)

# Request validation is automatic
class CreateAssessmentRequest(BaseModel):
    org_id: str
    include_recommendations: bool = True

# Response validation is automatic
@app.post("/api/v1/assessments", response_model=ScaleScoreReport)
async def create_assessment(
    request: CreateAssessmentRequest,
    service: AssessmentService = Depends(get_assessment_service)
) -> ScaleScoreReport:
    return await service.run_assessment(request.org_id)
```

## Related Decisions

- ADR-0001: Pydantic v2 for Models (native integration)
- ADR-0004: Repository Pattern (injected via FastAPI Depends)

## Notes

- FastAPI documentation: https://fastapi.tiangolo.com/
- Starlette (underlying framework): https://www.starlette.io/
