# ScaleScore Architecture

> **Last Updated**: January 2026  
> **Status**: Living Document  
> **Owner**: Engineering

---

## Table of Contents

1. [Architecture Principles](#1-architecture-principles)
2. [System Overview](#2-system-overview)
3. [Layer Architecture](#3-layer-architecture)
4. [Data Architecture](#4-data-architecture)
5. [Integration Architecture](#5-integration-architecture)
6. [Scalability Design](#6-scalability-design)
7. [Technology Decisions](#7-technology-decisions)
8. [Future Considerations](#8-future-considerations)

---

## 1. Architecture Principles

These principles guide all architectural decisions. They are ordered by priority when conflicts arise.

### 1.1 Security by Design

> **"Assume breach. Protect data. Earn trust."**

- **Data classification enforced in code**: Sensitive fields (revenue, headcount, financials) are marked and handled appropriately
- **Audit logging**: All state-changing operations produce audit records
- **Principle of least privilege**: Components have minimal required permissions
- **Defense in depth**: Multiple security layers, not single points of protection
- **Secrets never in code**: All credentials via environment variables or secrets managers

**Architectural Implications:**
- Every model field classified as `public`, `internal`, or `confidential`
- Repository pattern enforces tenant isolation at data layer
- API responses filter fields based on caller permissions
- Logging infrastructure strips sensitive data automatically

### 1.2 Build for Scale

> **"Design for 100x. Implement for 10x. Validate at 1x."**

- **Horizontal over vertical**: Stateless services that scale out
- **Multi-tenancy native**: Tenant isolation is not an afterthought
- **Async by default**: Non-blocking I/O, background job processing
- **Database-aware design**: Query patterns considered during schema design

**Architectural Implications:**
- All database queries include `org_id` scoping (tenant isolation)
- No in-memory state that can't be reconstructed from database
- Background job infrastructure for long-running operations
- Connection pooling and query optimization from day one

### 1.3 Graceful Architecture

> **"Complexity is the enemy. Fight it relentlessly."**

- **Separation of concerns**: Clear boundaries between layers
- **Explicit over implicit**: No magic; behavior should be traceable
- **Interface-first design**: Define contracts before implementations
- **Composition over inheritance**: Flexible, testable components
- **Fail fast, recover gracefully**: Clear error handling and propagation

**Architectural Implications:**
- Strict layering: API → Service → Repository → Database
- Pydantic models as the single source of truth for data shapes
- Dependency injection for testability
- Comprehensive error types with actionable messages

### 1.4 Operational Excellence

> **"If it's not observable, it's not production-ready."**

- **Structured logging**: JSON logs with correlation IDs
- **Health checks**: Deep health checks that verify dependencies
- **Metrics exposure**: Key business and technical metrics
- **Graceful degradation**: Partial functionality over complete failure

**Architectural Implications:**
- OpenTelemetry integration for tracing
- Prometheus metrics endpoint
- Circuit breakers for external dependencies
- Feature flags for gradual rollouts

---

## 2. System Overview

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SCALESCORE                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────────────────────────────────────────────┐ │
│  │   Clients   │    │                    API Layer                        │ │
│  │             │    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │ │
│  │ • Streamlit │───▶│  │   FastAPI   │  │  WebSocket  │  │   GraphQL   │  │ │
│  │ • React App │    │  │   REST API  │  │  (Future)   │  │  (Future)   │  │ │
│  │ • API Users │    │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │ │
│  └─────────────┘    │         │                │                │         │ │
│                     └─────────┼────────────────┼────────────────┼─────────┘ │
│                               │                │                │           │
│                               ▼                ▼                ▼           │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         Service Layer                                 │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │   │
│  │  │ Assessment │  │  Scoring   │  │ Bottleneck │  │ Recommendation │  │   │
│  │  │  Service   │  │  Engine    │  │  Detector  │  │    Engine      │  │   │
│  │  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └───────┬────────┘  │   │
│  │        │               │               │                 │           │   │
│  │        └───────────────┼───────────────┼─────────────────┘           │   │
│  │                        │               │                             │   │
│  └────────────────────────┼───────────────┼─────────────────────────────┘   │
│                           │               │                                  │
│  ┌────────────────────────┼───────────────┼─────────────────────────────┐   │
│  │                        ▼               ▼                              │   │
│  │                    Repository Layer                                   │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │   │
│  │  │Organization│  │   Entity   │  │ Assessment │  │    Audit       │  │   │
│  │  │    Repo    │  │    Repo    │  │    Repo    │  │    Repo        │  │   │
│  │  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └───────┬────────┘  │   │
│  │        │               │               │                 │           │   │
│  └────────┼───────────────┼───────────────┼─────────────────┼───────────┘   │
│           │               │               │                 │               │
│  ┌────────┼───────────────┼───────────────┼─────────────────┼───────────┐   │
│  │        ▼               ▼               ▼                 ▼           │   │
│  │                      Data Layer                                      │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │                   PostgreSQL / SQLite                         │   │   │
│  │  │  • Organizations  • Entities  • Reports  • Audit Logs        │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        Connectors                                     │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────────┐  ┌─────────────────────┐  │   │
│  │  │   CSV   │  │  HRIS   │  │     ERP     │  │   OpsOrchestra      │  │   │
│  │  │ Import  │  │ (Future)│  │  (Future)   │  │   (Bidirectional)   │  │   │
│  │  └─────────┘  └─────────┘  └─────────────┘  └─────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Responsibilities

| Component | Responsibility | Dependencies |
|-----------|---------------|--------------|
| **API Layer** | Request handling, auth, validation, response formatting | Service Layer |
| **Assessment Service** | Orchestrates full assessment workflow | All engines, repositories |
| **Scoring Engine** | Calculates readiness scores from constraints/risks | Models only (stateless) |
| **Bottleneck Detector** | Identifies capacity constraints and cascade risks | Models only (stateless) |
| **Recommendation Engine** | Generates prioritized action items | Models only (stateless) |
| **Repository Layer** | Data access, tenant isolation, query optimization | Database |
| **Connectors** | External data ingestion and synchronization | External systems |

---

## 3. Layer Architecture

### 3.1 API Layer

**Responsibilities:**
- HTTP request/response handling
- Authentication and authorization
- Request validation (Pydantic)
- Rate limiting
- API versioning
- Error response formatting

**Design Decisions:**
- FastAPI for async support and automatic OpenAPI docs
- Pydantic v2 for request/response validation
- API versioning via URL path (`/api/v1/...`)
- Correlation ID injection for request tracing

**File Structure:**
```
src/scalescore/api/
├── __init__.py
├── main.py              # FastAPI app factory
├── dependencies.py      # Dependency injection
├── middleware/
│   ├── auth.py          # Authentication middleware
│   ├── logging.py       # Request/response logging
│   └── tenant.py        # Tenant context extraction
├── routers/
│   ├── assessments.py   # Assessment endpoints
│   ├── organizations.py # Organization CRUD
│   ├── entities.py      # Entity management
│   └── health.py        # Health checks
└── schemas/
    ├── requests.py      # Request models
    └── responses.py     # Response models
```

### 3.2 Service Layer

**Responsibilities:**
- Business logic orchestration
- Transaction management
- Cross-cutting concerns (logging, metrics)
- Service-to-service communication

**Design Decisions:**
- Services are stateless and receive dependencies via constructor
- Each service has a single, cohesive responsibility
- Services return domain models, not database models
- Exceptions are domain-specific (e.g., `AssessmentNotFoundError`)

**Pattern:**
```python
class AssessmentService:
    def __init__(
        self,
        org_repo: OrganizationRepository,
        entity_repo: EntityRepository,
        report_repo: ReportRepository,
        scoring_engine: ScoringEngine,
        bottleneck_detector: BottleneckDetector,
        recommender: RecommendationEngine,
    ) -> None:
        self._org_repo = org_repo
        self._entity_repo = entity_repo
        self._report_repo = report_repo
        self._scoring = scoring_engine
        self._detector = bottleneck_detector
        self._recommender = recommender

    async def run_assessment(self, org_id: str) -> ScaleScoreReport:
        """Orchestrates full assessment workflow."""
        # 1. Load organization and entities
        # 2. Run bottleneck detection
        # 3. Calculate scores
        # 4. Generate recommendations
        # 5. Persist report
        # 6. Return result
```

### 3.3 Repository Layer

**Responsibilities:**
- Data access abstraction
- Tenant isolation enforcement
- Query optimization
- Connection management

**Design Decisions:**
- Repository pattern for all data access
- Abstract base class defines interface; concrete implementations for SQL/OpsOrchestra
- All queries scoped by `org_id` (tenant isolation enforced here)
- Soft deletes for audit trail preservation

**Pattern:**
```python
from abc import ABC, abstractmethod

class OrganizationRepository(ABC):
    @abstractmethod
    async def get_by_id(self, org_id: str) -> Organization | None:
        """Retrieve organization by ID."""
        ...

    @abstractmethod
    async def create(self, org: Organization) -> Organization:
        """Create new organization."""
        ...

    @abstractmethod
    async def list_for_org(self, org_id: str) -> list[Organization]:
        """List organizations in current org context."""
        ...

class SQLOrganizationRepository(OrganizationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, org_id: str) -> Organization | None:
        # Implementation with proper tenant scoping
        ...
```

### 3.4 Domain Models

**Location:** `src/scalescore/models/`

**Design Decisions:**
- Pydantic v2 models are the single source of truth
- Models are immutable where possible (frozen dataclasses for configs)
- Validation logic lives in models, not services
- Enums for all categorical fields (no magic strings)

**Model Categories:**
| Category | Location | Examples |
|----------|----------|----------|
| Core Entities | `models/core.py` | Organization, Team, System, Vendor, Facility |
| Scaling Models | `models/scaling.py` | GrowthSignal, CapacityConstraint, RiskIndicator, ReadinessScore |
| API Schemas | `api/schemas/` | Request/response shapes (may differ from domain models) |
| Database Models | `storage/models.py` | SQLAlchemy models (future) |

---

## 4. Data Architecture

### 4.1 Data Classification

All data is classified into sensitivity levels:

| Level | Description | Examples | Handling |
|-------|-------------|----------|----------|
| **Public** | No sensitivity | Entity names, types | No restrictions |
| **Internal** | Business-sensitive | Scores, recommendations | Tenant-isolated, audit logged |
| **Confidential** | Highly sensitive | Revenue, headcount, financials | Encrypted at rest, masked in logs, strict access |

### 4.2 Entity Relationship Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TENANT BOUNDARY                                │
│                                                                          │
│  ┌──────────────┐                                                       │
│  │ Organization │ 1                                                     │
│  │              │─────────────────────────────────────┐                 │
│  │  • id (PK)   │                                     │                 │
│  │  • name      │                                     │                 │
│  │  • headcount │                                     │                 │
│  │  • revenue   │                                     │                 │
│  └──────┬───────┘                                     │                 │
│         │                                             │                 │
│         │ 1:N                                         │ 1:N             │
│         ▼                                             ▼                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │     Team     │  │    System    │  │    Vendor    │  │  Facility   │ │
│  │              │  │              │  │              │  │             │ │
│  │  • org_id    │  │  • org_id    │  │  • org_id    │  │  • org_id   │ │
│  │  • parent_id │  │  • vendor_id │  │  • is_critic │  │  • capacity │ │
│  │  • function  │  │  • capacity  │  │  • contract  │  │  • location │ │
│  └──────────────┘  └──────┬───────┘  └──────────────┘  └─────────────┘ │
│                           │                                             │
│                           │ N:M (dependencies)                          │
│                           ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     Dependency Graph                              │  │
│  │                (System → System, System → Vendor)                 │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                       Growth Signals                              │  │
│  │                                                                   │  │
│  │  • org_id  • signal_type  • magnitude  • target_date             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Assessment Reports (Immutable)                 │  │
│  │                                                                   │  │
│  │  • report_id  • org_id  • generated_at  • scores (JSON)          │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Data Storage Strategy

| Data Type | Storage | Rationale |
|-----------|---------|-----------|
| Entity data | PostgreSQL (relational) | Structured, queryable, transactional |
| Assessment reports | PostgreSQL (JSONB) | Immutable snapshots, schema flexibility |
| Dependency graphs | PostgreSQL + NetworkX | Relational for persistence, in-memory for analysis |
| Audit logs | PostgreSQL (append-only) | Compliance, immutable history |
| Session cache | Redis (future) | Performance, stateless scaling |

### 4.4 Multi-Tenancy Model

**Approach:** Shared database, org-discriminator column

Every table includes `org_id` as the tenant discriminator. All queries are automatically scoped.

```python
# Repository base enforces tenant isolation
class OrgScopedRepository(ABC):
    def __init__(self, session: AsyncSession, org_id: str) -> None:
        self._session = session
        self._org_id = org_id

    def _apply_org_filter(self, query: Select) -> Select:
        """Applied to ALL queries automatically."""
        return query.where(self._model.org_id == self._org_id)
```

**Why shared database?**
- Simpler operations (single database to manage)
- Efficient resource utilization
- Adequate isolation with row-level security
- Can migrate to dedicated databases later if needed

---

## 5. Integration Architecture

### 5.1 OpsOrchestra Integration

ScaleScore is designed for bidirectional integration with OpsOrchestra:

```
┌─────────────────────┐                    ┌─────────────────────┐
│    OpsOrchestra     │                    │     ScaleScore      │
│                     │                    │                     │
│  ┌───────────────┐  │   Entity Sync      │  ┌───────────────┐  │
│  │  Knowledge    │──┼───────────────────▶│  │   Connector   │  │
│  │    Graph      │  │                    │  │               │  │
│  │               │◀─┼───────────────────-│  │               │  │
│  └───────────────┘  │   Risk Indicators  │  └───────────────┘  │
│                     │                    │                     │
│  ┌───────────────┐  │                    │  ┌───────────────┐  │
│  │    Webhook    │──┼───────────────────▶│  │   Webhook     │  │
│  │   Publisher   │  │  Entity Changes    │  │   Handler     │  │
│  └───────────────┘  │                    │  └───────────────┘  │
│                     │                    │                     │
└─────────────────────┘                    └─────────────────────┘
```

**Integration Modes:**

| Mode | Data Flow | Use Case |
|------|-----------|----------|
| **Standalone** | CSV/API → ScaleScore | Independent usage |
| **Read-only** | OpsOrchestra → ScaleScore | Use OpsOrch as data source |
| **Bidirectional** | OpsOrchestra ↔ ScaleScore | Full integration, risk feedback |

### 5.2 Connector Interface

All data sources implement a common interface:

```python
from abc import ABC, abstractmethod

class DataConnector(ABC):
    """Base interface for all data connectors."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to data source."""
        ...

    @abstractmethod
    async def fetch_organizations(self) -> list[Organization]:
        """Fetch all organizations from source."""
        ...

    @abstractmethod
    async def fetch_entities(self, org_id: str) -> EntityBundle:
        """Fetch all entities for an organization."""
        ...

    @abstractmethod
    async def health_check(self) -> ConnectorHealth:
        """Check connector health status."""
        ...
```

---

## 6. Scalability Design

### 6.1 Scaling Dimensions

| Dimension | Current Design | Scale Strategy |
|-----------|---------------|----------------|
| **Users** | Single instance | Horizontal API scaling behind load balancer |
| **Organizations** | In-memory processing | Background job queue for large assessments |
| **Data volume** | Full load | Pagination, streaming, incremental sync |
| **Concurrent assessments** | Sequential | Async processing with Celery/RQ |

### 6.2 Stateless Design

All services are designed to be stateless:

- No in-memory caching of business data
- Session state in database or Redis
- Any instance can handle any request
- Horizontal scaling = add more instances

### 6.3 Database Scaling Path

```
Phase 1 (MVP):       SQLite (dev) → PostgreSQL (single instance)
Phase 2 (Growth):    PostgreSQL with read replicas
Phase 3 (Scale):     PostgreSQL with connection pooling (PgBouncer)
Phase 4 (Enterprise): Consider partitioning by tenant or time-series data
```

### 6.4 Performance Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| Assessment API response | < 5s for < 100 entities | Interactive UX |
| Assessment API response | < 30s for < 1000 entities | Acceptable for background |
| Dashboard load time | < 2s | User experience |
| API p99 latency | < 500ms (simple endpoints) | Responsive feel |

---

## 7. Technology Decisions

All significant technology decisions are documented as ADRs. Summary:

| Decision | Choice | Key Rationale |
|----------|--------|---------------|
| Language | Python 3.11+ | Ecosystem, team expertise, OpsOrchestra alignment |
| API Framework | FastAPI | Async, OpenAPI, Pydantic integration |
| Data Validation | Pydantic v2 | Performance, type safety, FastAPI integration |
| Database | PostgreSQL | Reliability, JSONB support, scaling path |
| Graph Analysis | NetworkX | Dependency graph algorithms, Python native |
| UI (MVP) | Streamlit | Rapid iteration, data-focused |
| UI (Production) | React + TypeScript | Production-grade, team expertise |
| Task Queue | Celery (future) | Mature, well-supported |
| Caching | Redis (future) | Performance, session storage |

See [ADR Index](./adr/README.md) for detailed decision records.

---

## 8. Future Considerations

### 8.1 Known Evolution Points

| Area | Current State | Future Direction |
|------|--------------|------------------|
| Database | SQLite dev, Postgres planned | Add read replicas, connection pooling |
| Authentication | Not implemented | JWT + OAuth2/OIDC for SSO |
| Background jobs | Sync processing | Celery + Redis for async assessments |
| Caching | None | Redis for session and computed data |
| Search | Basic | Elasticsearch for report/entity search |
| AI/ML | Rule-based scoring | ML-based risk prediction, NLP for recommendations |

### 8.2 Architecture Decision Queue

Decisions to be made and documented:

1. **Database ORM choice** - SQLAlchemy vs. alternative
2. **Authentication strategy** - Build vs. buy (Auth0, Clerk)
3. **Background job infrastructure** - Celery vs. alternatives
4. **Deployment strategy** - Containers, orchestration, cloud provider
5. **Observability stack** - Logging, metrics, tracing infrastructure

---

## Appendix A: Architecture Review Checklist

Before merging significant changes, verify:

- [ ] Change follows layer separation (API → Service → Repository → DB)
- [ ] New data is classified (public/internal/confidential)
- [ ] Tenant isolation maintained (queries scoped by org_id)
- [ ] Error handling is explicit (no silent failures)
- [ ] Sensitive data excluded from logs
- [ ] ADR created for architectural decisions
- [ ] Performance implications considered
- [ ] Tests cover new functionality

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **Tenant** | An isolated customer instance (mapped to Organization in MVP) |
| **Entity** | A core business object (Organization, Team, System, Vendor, Facility) |
| **Assessment** | The process of analyzing an organization's scale readiness |
| **Report** | Immutable snapshot of assessment results |
| **Connector** | Component that imports data from external sources |
