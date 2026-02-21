# ADR-0001: Use Pydantic v2 for Data Models

**Status**: Accepted  
**Date**: 2026-01-15  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore needs a data validation and serialization layer for:
- API request/response validation
- Domain model definition
- Configuration management
- Data import validation (CSV, API)

We need to choose a library that provides:
- Strong type safety
- Runtime validation
- JSON serialization
- Good IDE support
- Performance at scale

Additionally, ScaleScore is designed for future integration with OpsOrchestra, which uses Pydantic models.

## Decision Drivers

- **Type safety**: Catch errors at development time
- **Validation**: Ensure data integrity at runtime
- **Performance**: Handle large datasets efficiently (1000+ entities)
- **Ecosystem**: Integration with FastAPI, other tools
- **OpsOrchestra compatibility**: Shared model definitions

## Considered Options

### Option 1: Pydantic v2

Python data validation using type annotations with Rust-based core for performance.

**Pros:**
- Native FastAPI integration (request/response validation automatic)
- Pydantic v2 is 5-50x faster than v1
- Excellent type hints and IDE support
- Built-in JSON Schema generation
- OpsOrchestra uses Pydantic

**Cons:**
- Breaking changes from v1 (not relevant for new project)
- Some advanced features have learning curve

### Option 2: dataclasses + marshmallow

Standard library dataclasses with marshmallow for serialization.

**Pros:**
- dataclasses is standard library
- marshmallow is mature and flexible

**Cons:**
- Two libraries to maintain
- No native FastAPI integration
- More boilerplate code
- OpsOrchestra uses Pydantic (impedance mismatch)

### Option 3: attrs + cattrs

attrs for class definition, cattrs for serialization.

**Pros:**
- Very performant
- Highly customizable

**Cons:**
- Less ecosystem support
- No native FastAPI integration
- Smaller community
- OpsOrchestra compatibility issues

## Decision

**Use Pydantic v2** for all data models in ScaleScore.

Rationale:
1. Native FastAPI integration eliminates boilerplate
2. Performance improvements in v2 address scale concerns
3. OpsOrchestra compatibility enables future integration
4. Single library for validation, serialization, and settings

## Consequences

### Positive
- Consistent model definition across API, domain, and storage
- Automatic OpenAPI schema generation
- Strong type safety with IDE support
- Easy OpsOrchestra integration path

### Negative
- All developers must learn Pydantic patterns
- Some edge cases require understanding validators and serializers

### Neutral
- Requires Python 3.11+ for best performance

## Implementation Notes

```python
# Standard model pattern
from pydantic import BaseModel, Field
from datetime import datetime

class Organization(BaseModel):
    id: str
    name: str
    headcount_current: int = Field(ge=0)
    revenue_current: float = Field(ge=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
    )
```

## Related Decisions

- ADR-0002: FastAPI for API Layer (Pydantic integration is key factor)

## Notes

- Pydantic v2 documentation: https://docs.pydantic.dev/latest/
- Migration from v1: Not applicable (greenfield project)
