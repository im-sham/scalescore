# ADR-0006: PostgreSQL as Primary Database

**Status**: Accepted  
**Date**: 2026-01-15  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore needs persistent storage for:
- Organizations and entities (structured data)
- Assessment reports (semi-structured, immutable)
- Audit logs (append-only)
- User and session data (future)
- Score history (time-series-like)

The database must support:
- Complex queries (filtering, aggregation, joins)
- JSON storage for flexible schemas
- Row-level security for multi-tenancy
- High reliability and data integrity
- Reasonable performance at scale

## Decision Drivers

- **Reliability**: Data must not be lost
- **Query flexibility**: Complex business queries
- **JSON support**: Flexible schema for reports
- **Security features**: Row-level security for multi-tenancy
- **Ecosystem**: Client libraries, ORMs, tooling
- **Operational maturity**: Proven in production
- **Cost**: Reasonable for startup stage

## Considered Options

### Option 1: PostgreSQL

Industry-standard open-source relational database.

**Pros:**
- ACID compliance, excellent reliability
- JSONB for flexible schema storage
- Row-Level Security for multi-tenancy
- Excellent Python support (asyncpg, SQLAlchemy)
- Rich feature set (full-text search, extensions)
- Widely supported by cloud providers
- Strong community and ecosystem

**Cons:**
- Requires more setup than SQLite
- Operational overhead (backups, monitoring)
- Not as simple for local development

### Option 2: MySQL/MariaDB

Popular open-source relational database.

**Pros:**
- Widely used, well-understood
- Good performance
- Cloud support

**Cons:**
- JSON support less mature than PostgreSQL
- No native row-level security
- Fewer advanced features

### Option 3: SQLite

Embedded database, file-based.

**Pros:**
- Zero configuration
- Perfect for development
- No external process

**Cons:**
- No concurrent writes (single writer)
- No row-level security
- Not suitable for multi-tenant production
- Limited scale

### Option 4: MongoDB

Document database.

**Pros:**
- Flexible schema
- Easy JSON storage
- Good for rapid iteration

**Cons:**
- Less mature ACID (improved, but still...)
- No foreign keys (harder to maintain integrity)
- Different query paradigm (team learning)
- Relational queries are awkward

### Option 5: CockroachDB/YugabyteDB

Distributed SQL databases.

**Pros:**
- PostgreSQL compatible
- Horizontal scaling built-in
- Global distribution

**Cons:**
- Overkill for current scale
- Higher complexity
- Higher cost

## Decision

**Use PostgreSQL** with SQLite for local development.

| Environment | Database |
|-------------|----------|
| Local development | SQLite (via SQLAlchemy) |
| CI/CD testing | PostgreSQL (Docker) |
| Staging | PostgreSQL (managed) |
| Production | PostgreSQL (managed, e.g., AWS RDS, Cloud SQL) |

### Rationale

1. **JSONB**: Store assessment reports as immutable JSON snapshots
2. **Row-Level Security**: Defense in depth for multi-tenancy
3. **Reliability**: ACID guarantees protect business-critical data
4. **Ecosystem**: SQLAlchemy 2.0 with asyncpg for async
5. **Cloud support**: All major clouds offer managed PostgreSQL
6. **Path to scale**: Read replicas, connection pooling well-understood

## Consequences

### Positive
- Reliable, proven database technology
- JSONB handles report schema flexibility
- RLS adds tenant isolation layer
- Excellent Python async support
- Clear scaling path

### Negative
- Requires database server in production
- More setup than SQLite for contributors
- Operational overhead (backups, monitoring, upgrades)

### Neutral
- SQLite for dev means some feature parity considerations
- Need ORM that abstracts differences (SQLAlchemy)

## Implementation Notes

### Development Setup

```bash
# Use SQLite for local development (no setup required)
DATABASE_URL=sqlite+aiosqlite:///./scalescore.db

# Or run PostgreSQL in Docker
docker run -d --name scalescore-db \
  -e POSTGRES_USER=scalescore \
  -e POSTGRES_PASSWORD=dev \
  -e POSTGRES_DB=scalescore \
  -p 5432:5432 \
  postgres:16

DATABASE_URL=postgresql+asyncpg://scalescore:dev@localhost/scalescore
```

### Schema Design

```sql
-- Example: Assessment reports as JSONB
CREATE TABLE assessment_reports (
    id UUID PRIMARY KEY,
    org_id VARCHAR(100) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    report_version VARCHAR(20) NOT NULL,
    report_data JSONB NOT NULL,  -- Full report as JSON
    
    -- Indexes
    CONSTRAINT fk_org FOREIGN KEY (org_id) REFERENCES organizations(id)
);

CREATE INDEX idx_reports_org ON assessment_reports(org_id);
CREATE INDEX idx_reports_generated ON assessment_reports(generated_at);

-- Row-Level Security
ALTER TABLE assessment_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON assessment_reports
    USING (org_id = current_setting('app.org_id'));
```

### SQLAlchemy Configuration

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)
```

## Related Decisions

- ADR-0004: Repository Pattern (abstracts database access)
- ADR-0005: Multi-Tenancy (uses RLS for defense in depth)

## Notes

- Consider pgvector extension for future ML features
- Consider TimescaleDB extension for score history (future)
- Managed PostgreSQL recommended for production (RDS, Cloud SQL, Neon)
