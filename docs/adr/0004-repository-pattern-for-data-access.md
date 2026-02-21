# ADR-0004: Repository Pattern for Data Access

**Status**: Accepted  
**Date**: 2026-01-15  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore needs a data access layer that:
- Abstracts database implementation from business logic
- Enforces tenant isolation (multi-tenancy)
- Supports multiple data sources (SQL, OpsOrchestra, CSV)
- Enables testing without database dependencies
- Scales without major refactoring

Currently, we have direct data loading in the assessment code. As we add database persistence, we need a clean abstraction.

## Decision Drivers

- **Testability**: Mock data access in unit tests
- **Flexibility**: Swap implementations (SQLite → PostgreSQL → OpsOrchestra)
- **Security**: Enforce tenant isolation at data layer
- **Separation of concerns**: Keep business logic database-agnostic
- **Scale preparation**: Design for future distributed data

## Considered Options

### Option 1: Repository Pattern

Abstract data access behind interfaces, with concrete implementations.

```python
class OrganizationRepository(ABC):
    @abstractmethod
    async def get_by_id(self, org_id: str) -> Organization | None: ...

class SQLOrganizationRepository(OrganizationRepository):
    async def get_by_id(self, org_id: str) -> Organization | None:
        # SQL implementation
```

**Pros:**
- Clear abstraction boundary
- Easy to swap implementations
- Natural place to enforce tenant isolation
- Simple to mock for testing

**Cons:**
- More code than direct access
- Can become verbose with many entities

### Option 2: Active Record Pattern

Entities know how to save/load themselves.

**Pros:**
- Less code for simple cases
- Familiar to Rails/Django developers

**Cons:**
- Couples domain models to persistence
- Harder to test
- Tenant isolation harder to enforce consistently
- Doesn't support multiple backends well

### Option 3: Query Builder / ORM Direct

Use ORM (SQLAlchemy) directly in services.

**Pros:**
- Less abstraction code
- Full ORM power available

**Cons:**
- Leaks persistence concerns into business logic
- Harder to swap backends
- Tenant isolation must be remembered everywhere
- Testing requires database or complex mocking

### Option 4: CQRS (Command Query Responsibility Segregation)

Separate read and write models.

**Pros:**
- Optimal for complex read patterns
- Enables event sourcing

**Cons:**
- Overkill for current complexity
- More infrastructure
- Higher learning curve

## Decision

**Use Repository Pattern** with the following structure:

1. **Abstract Repository Interface**: Defines contract per entity type
2. **Tenant-Scoped Base**: Base class that enforces org_id scoping
3. **Concrete Implementations**: SQL, OpsOrchestra, CSV connectors

```python
# Base enforces tenant isolation
class OrgScopedRepository(ABC):
    def __init__(self, org_id: str) -> None:
        self._org_id = org_id

# Interface per entity
class OrganizationRepository(OrgScopedRepository):
    @abstractmethod
    async def get_by_id(self, org_id: str) -> Organization | None: ...
    @abstractmethod
    async def list_all(self) -> list[Organization]: ...
    @abstractmethod
    async def save(self, org: Organization) -> Organization: ...

# SQL implementation
class SQLOrganizationRepository(OrganizationRepository):
    def __init__(self, session: AsyncSession, org_id: str) -> None:
        super().__init__(org_id)
        self._session = session

    async def get_by_id(self, org_id: str) -> Organization | None:
        query = select(OrgModel).where(
            OrgModel.id == org_id,
            OrgModel.org_id == self._org_id  # ALWAYS included
        )
        result = await self._session.execute(query)
        row = result.scalar_one_or_none()
        return Organization.model_validate(row) if row else None
```

## Consequences

### Positive
- Tenant isolation is structural, not accidental
- Easy to add OpsOrchestra backend without changing services
- Unit tests don't need database
- Clear separation of persistence and business logic

### Negative
- More code per entity type
- Must maintain interface + implementation(s)
- Some duplication across entity repositories

### Neutral
- Need to decide on ORM (SQLAlchemy) separately
- Transaction management lives in service layer

## Mitigation for Verbosity

Use a generic base repository for common CRUD:

```python
class BaseRepository(OrgScopedRepository, Generic[T]):
    async def get_by_id(self, id: str) -> T | None: ...
    async def list_all(self) -> list[T]: ...
    async def save(self, entity: T) -> T: ...
    async def delete(self, id: str) -> bool: ...

class OrganizationRepository(BaseRepository[Organization]):
    # Only add org-specific methods
    async def get_by_name(self, name: str) -> Organization | None: ...
```

## Related Decisions

- ADR-0005: Multi-Tenancy Strategy (org_id comes from here)
- ADR-0006: PostgreSQL as Primary Database (main implementation)

## Notes

- Consider using SQLAlchemy 2.0 with async session
- Repository should return domain models, not ORM models
