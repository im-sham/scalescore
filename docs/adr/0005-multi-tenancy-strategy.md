# ADR-0005: Shared Database Multi-Tenancy Strategy

**Status**: Accepted  
**Date**: 2026-01-15  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore will serve multiple organizations (tenants). We need a multi-tenancy strategy that:

- Isolates data between tenants completely
- Scales to hundreds of tenants
- Maintains query performance
- Enables compliance with data residency requirements (future)
- Supports both standalone and OpsOrchestra-integrated modes

## Decision Drivers

- **Data isolation**: Tenants must never see each other's data
- **Operational simplicity**: Minimize infrastructure complexity
- **Cost efficiency**: Don't over-provision for early stage
- **Future flexibility**: Path to stronger isolation if needed
- **Performance**: Query performance must not degrade with tenant count

## Considered Options

### Option 1: Shared Database, Discriminator Column

All tenants in one database, `org_id` column on every table.

```sql
SELECT * FROM organizations WHERE org_id = 'org_abc' AND id = 'org_1';
```

**Pros:**
- Simplest to operate (one database)
- Efficient resource utilization
- Easy backup/restore for whole system
- Works with any database

**Cons:**
- Must enforce org_id in every query (risk of bugs)
- Single point of failure for all tenants
- Noisy neighbor potential
- Cross-tenant analytics harder to prevent

### Option 2: Schema-Per-Tenant

Each tenant gets a PostgreSQL schema within shared database.

```sql
SET search_path TO tenant_abc;
SELECT * FROM organizations WHERE id = 'org_1';
```

**Pros:**
- Stronger logical isolation
- Easy to drop tenant (drop schema)
- Some performance isolation

**Cons:**
- Schema migration complexity (run against all schemas)
- Connection pooling complexity
- PostgreSQL-specific
- Hundreds of schemas can be unwieldy

### Option 3: Database-Per-Tenant

Each tenant gets dedicated database instance.

**Pros:**
- Strongest isolation
- Easy data residency compliance
- Independent scaling
- Easy tenant deletion

**Cons:**
- High operational overhead
- Expensive for many small tenants
- Complex cross-tenant operations (analytics, support)
- Connection management at scale

### Option 4: Hybrid (Shared → Dedicated)

Start shared, offer dedicated for enterprise/compliance.

**Pros:**
- Best of both worlds
- Scales with customer needs
- Revenue-aligned (dedicated costs more)

**Cons:**
- Must support two models
- More complex codebase

## Decision

**Use Shared Database with Discriminator Column** (Option 1) with:

1. Repository pattern enforcing tenant isolation (ADR-0004)
2. Row-Level Security (RLS) as defense in depth
3. Clear path to Schema-Per-Tenant or Database-Per-Tenant for enterprise

### Implementation

```python
# Org ID extracted from JWT in middleware
@app.middleware("http")
async def tenant_context(request: Request, call_next):
    token = get_token(request)
    request.state.org_id = token.get("org_id")
    response = await call_next(request)
    return response

# Repository constructor receives org_id
class SQLOrganizationRepository:
    def __init__(self, session: AsyncSession, org_id: str):
        self._session = session
        self._org_id = org_id
    
    async def get_by_id(self, org_id: str) -> Organization | None:
        query = select(OrgModel).where(
            OrgModel.id == org_id,
            OrgModel.org_id == self._org_id  # ENFORCED HERE
        )
        ...
```

### Row-Level Security (Defense in Depth)

```sql
-- Additional protection at database level
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_isolation ON organizations
    USING (org_id = current_setting('app.org_id'));

-- Set in each connection
SET app.org_id = 'org_abc';
```

## Consequences

### Positive
- Simple operations (one database)
- Cost-effective for early stage
- Repository pattern makes tenant isolation structural
- RLS provides defense in depth

### Negative
- Must be vigilant about org_id in all queries
- Noisy neighbor risk (mitigated by indexing, rate limiting)
- Single database is single point of failure

### Neutral
- Clear migration path to schema or database per tenant
- Need index on org_id for all tables

## Organization Context Strategy

| Mode | Org ID Source |
|------|------------------|
| **Standalone** | `org_id` (organization is the tenant) |
| **OpsOrchestra** | `org_id` mapped from OpsOrchestra tenant context (may have multiple orgs) |

MVP uses org_id as the tenant discriminator. OpsOrchestra integration may introduce a separate tenant concept, but ScaleScore will map it to org_id for internal consistency.

## Related Decisions

- ADR-0004: Repository Pattern (enforces tenant isolation)
- ADR-0006: PostgreSQL (supports RLS)

## Notes

- All tables must have `org_id` column indexed
- Queries without tenant filter should fail code review
- Consider tenant-aware connection pooling (future)
