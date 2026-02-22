# ScaleScore Technical Specification

**Version:** 0.1.0  
**Author:** Shamim Rehman  
**Created:** January 2026  
**Status:** Draft

---

## Executive Summary

ScaleScore is an operational readiness prediction system that identifies scaling bottlenecks before they occur. It combines organizational data with heuristic models derived from 15+ years of scaling experience to produce actionable readiness scores and recommendations.

**Core Value Proposition:** "Know where you'll break before you break."

---

## 1. Problem Statement

High-growth companies consistently encounter the same failure modes:
- Hiring plans that outpace real estate/facilities capacity
- Systems that don't scale with transaction volume
- Vendor dependencies that become single points of failure
- Governance structures that lag organizational complexity
- Finance/accounting infrastructure that breaks at scale

These failures are predictable but rarely predicted. Leaders react to fires instead of preventing them.

---

## 2. Solution Overview

ScaleScore ingests organizational data across multiple dimensions and produces:

1. **Readiness Scores** (0-100) by functional area
2. **Bottleneck Predictions** with timeline estimates
3. **Risk Heat Maps** visualizing constraint interdependencies
4. **Actionable Recommendations** with effort/impact scoring

---

## 3. Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ScaleScore                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Connectors  │  │    Core      │  │         API            │ │
│  │              │  │   Engine     │  │                        │ │
│  │ • CSV Import │  │              │  │ • FastAPI REST         │ │
│  │ • HRIS       │──│ • Scoring    │──│ • WebSocket (realtime) │ │
│  │ • ERP        │  │ • Prediction │  │ • GraphQL (future)     │ │
│  │ • OpsOrch*   │  │ • Recommend  │  │                        │ │
│  └──────────────┘  └──────────────┘  └────────────────────────┘ │
│          │                │                      │               │
│          ▼                ▼                      ▼               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Data Layer                             │   │
│  │                                                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │   │
│  │  │   Models    │  │  Constraint │  │   Time Series   │   │   │
│  │  │  (Pydantic) │  │    Graph    │  │     History     │   │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘   │   │
│  │                                                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                         UI                                │   │
│  │         Streamlit (MVP) → React Dashboard (v2)            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

* OpsOrchestra connector enables bidirectional data sharing
```

### 3.2 OpsOrchestra Integration Points

ScaleScore is designed to operate standalone OR as an OpsOrchestra module:

| Integration Point | Standalone Mode | Integrated Mode |
|-------------------|-----------------|-----------------|
| **Data Ingestion** | CSV, direct API | OpsOrchestra knowledge graph |
| **Entity Models** | Compatible Pydantic models | Shared model library |
| **Authentication** | Own JWT/API keys | OpsOrchestra tenant context |
| **Storage** | SQLite/Postgres | OpsOrchestra's existing DB |
| **UI** | Streamlit standalone | OpsOrchestra dashboard tab |

**Connector Interface (OpsOrchestra):**
```python
class OpsOrchestraConnector(BaseConnector):
    """
    Pulls organizational data from OpsOrchestra's knowledge graph.
    
    Entities mapped:
    - Organization → Organization
    - Team → Team  
    - System → System
    - Vendor → Vendor
    - Process → Process (for governance analysis)
    """
    
    async def fetch_org_structure(self, org_id: str) -> OrgStructure:
        """Fetch org hierarchy from OpsOrchestra graph."""
        ...
    
    async def fetch_systems_inventory(self, org_id: str) -> list[System]:
        """Fetch systems and their relationships."""
        ...
    
    async def push_risk_indicators(self, org_id: str, risks: list[RiskIndicator]):
        """Push ScaleScore findings back to OpsOrchestra for unified view."""
        ...
```

---

### 3.3 Data Governance & Source of Truth

ScaleScore uses a single authoritative model definition and clear persistence boundaries:

1. **Model Authority (SSOT):** The Pydantic models in `src/scalescore/models/` are the source of truth. This document provides illustrative excerpts only.
2. **Persistence:**
   - **Standalone:** Store organizations, entities, and assessments in SQLite (dev) or Postgres (prod).
   - **Integrated:** OpsOrchestra remains the system of record; ScaleScore loads entities into internal Pydantic models for scoring.
3. **Assessment Immutability:** `ScaleScoreReport` is stored as an immutable snapshot (JSON payload) keyed by `report_id` and timestamp.
4. **Schema Versioning:** Reports include `report_version` and `assessment_version` for compatibility tracking. Schema migration strategy to be finalized before production.

### 3.4 Security & Multi-tenancy

ScaleScore enforces strict tenant isolation and access control:

- **Tenant Isolation:** All queries and stored data are scoped by `org_id`.
- **Authentication:**
  - **Standalone:** JWT or API key auth (MVP); OAuth2/SSO in production.
  - **Integrated:** Trust OpsOrchestra session context and tenant claims.
- **Authorization:** Role-based access (viewer/editor/admin/owner) for data management, scoring configuration, and exports.
- **Data Privacy:** Sensitive fields (e.g., revenue, headcount plans) are treated as confidential and excluded from logs by default.

---

## 4. Data Model

### 4.1 Core Entities

These models are designed for compatibility with OpsOrchestra's EntityResponse pattern. The authoritative definitions live in `src/scalescore/models/` and may include additional fields beyond these excerpts.

```python
# src/scalescore/models/core.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class EntityType(str, Enum):
    ORGANIZATION = "organization"
    TEAM = "team"
    SYSTEM = "system"
    VENDOR = "vendor"
    FACILITY = "facility"
    ROLE = "role"
    PROCESS = "process"


class BaseEntity(BaseModel):
    """Base entity compatible with OpsOrchestra EntityResponse."""
    id: str
    type: EntityType
    name: str
    properties: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Organization(BaseEntity):
    type: EntityType = EntityType.ORGANIZATION
    headcount_current: int = 0
    headcount_plan: dict[str, int] = Field(default_factory=dict)  # {"Q1": 50, "Q2": 75, ...}
    revenue_current: float = 0.0
    revenue_plan: dict[str, float] = Field(default_factory=dict)
    burn_rate_monthly: float = 0.0
    runway_months: Optional[float] = None


class Team(BaseEntity):
    type: EntityType = EntityType.TEAM
    org_id: str
    parent_team_id: Optional[str] = None
    headcount_current: int = 0
    headcount_plan: dict[str, int] = Field(default_factory=dict)
    manager_id: Optional[str] = None
    function: str = ""  # engineering, sales, ops, etc.


class System(BaseEntity):
    type: EntityType = EntityType.SYSTEM
    org_id: str
    system_type: str = ""  # erp, crm, hris, custom, etc.
    vendor_id: Optional[str] = None
    capacity_current: Optional[float] = None  # transactions/day, users, etc.
    capacity_max: Optional[float] = None
    capacity_unit: str = ""  # "users", "transactions/day", "GB", etc.
    is_critical: bool = False
    dependencies: list[str] = Field(default_factory=list)  # system_ids


class Vendor(BaseEntity):
    type: EntityType = EntityType.VENDOR
    org_id: str
    vendor_type: str = ""  # saas, contractor, supplier, etc.
    contract_end_date: Optional[datetime] = None
    annual_cost: float = 0.0
    is_critical: bool = False
    alternatives: list[str] = Field(default_factory=list)


class Facility(BaseEntity):
    type: EntityType = EntityType.FACILITY
    org_id: str
    facility_type: str = ""  # office, warehouse, datacenter, etc.
    location: str = ""
    capacity_seats: int = 0
    capacity_used: int = 0
    lease_end_date: Optional[datetime] = None
    expansion_possible: bool = False
```

### 4.2 Scaling Entities (ScaleScore-specific)

```python
# src/scalescore/models/scaling.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConstraintType(str, Enum):
    CAPACITY = "capacity"          # System/facility capacity limits
    DEPENDENCY = "dependency"      # Vendor/system dependencies
    GOVERNANCE = "governance"      # Process/compliance gaps
    FINANCIAL = "financial"        # Budget/runway constraints
    TALENT = "talent"              # Hiring/skill gaps
    TIMELINE = "timeline"          # Schedule conflicts


class FunctionalArea(str, Enum):
    ENGINEERING = "engineering"
    SALES = "sales"
    OPERATIONS = "operations"
    FINANCE = "finance"
    PEOPLE = "people"
    FACILITIES = "facilities"
    LEGAL_COMPLIANCE = "legal_compliance"
    PRODUCT = "product"


class GrowthSignal(BaseModel):
    """Indicator of planned growth that drives capacity requirements."""
    id: str
    signal_type: str  # headcount_plan, revenue_target, product_launch, etc.
    target_date: datetime
    magnitude: float  # % increase or absolute value
    confidence: float = 0.8  # how certain is this signal
    source: str = ""  # where this came from (plan doc, exec input, etc.)
    affected_areas: list[FunctionalArea] = Field(default_factory=list)


class CapacityConstraint(BaseModel):
    """A limit that could block scaling."""
    id: str
    entity_id: str  # Reference to System, Facility, Team, etc.
    entity_type: str
    constraint_type: ConstraintType
    current_utilization: float  # 0.0 to 1.0
    projected_breach_date: Optional[datetime] = None
    breach_probability: float = 0.0  # 0.0 to 1.0
    mitigation_options: list[str] = Field(default_factory=list)
    mitigation_effort: str = ""  # low, medium, high
    mitigation_cost: Optional[float] = None


class RiskIndicator(BaseModel):
    """A specific identified risk with scoring."""
    id: str
    title: str
    description: str
    risk_level: RiskLevel
    functional_area: FunctionalArea
    constraint_type: ConstraintType
    affected_entities: list[str] = Field(default_factory=list)
    projected_impact_date: Optional[datetime] = None
    probability: float = 0.5
    impact_score: float = 0.5  # 0.0 to 1.0
    recommendations: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)  # Data points supporting this


class ReadinessScore(BaseModel):
    """Aggregate readiness score for a functional area."""
    org_id: str
    functional_area: FunctionalArea
    score: float  # 0-100
    sub_scores: dict[str, float] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)  # constraint_ids
    risks: list[str] = Field(default_factory=list)  # risk_ids
    trend: str = "stable"  # improving, stable, declining
    assessed_at: datetime = Field(default_factory=datetime.utcnow)


class ScaleScoreReport(BaseModel):
    """Complete assessment output."""
    org_id: str
    report_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    overall_score: float  # 0-100
    area_scores: list[ReadinessScore] = Field(default_factory=list)
    top_risks: list[RiskIndicator] = Field(default_factory=list)
    constraints: list[CapacityConstraint] = Field(default_factory=list)
    recommendations: list[dict] = Field(default_factory=list)
    growth_signals: list[GrowthSignal] = Field(default_factory=list)
```

---

## 5. Scoring Engine

### 5.1 Scoring Philosophy

ScaleScore uses a **constraint-based scoring model**:

1. **Identify Growth Signals** → What's the plan?
2. **Map Capacity Requirements** → What do we need to support it?
3. **Assess Current State** → What do we have?
4. **Detect Gaps** → Where are the constraints?
5. **Score Readiness** → How prepared are we?
6. **Recommend Actions** → What should we do?

### 5.2 Scoring Algorithm

```python
# src/scalescore/scoring/engine.py

class ScoringEngine:
    """
    Core scoring logic for operational readiness assessment.
    
    Scoring Formula:
    area_score = base_score - Σ(constraint_penalty) - Σ(risk_penalty)
    
    Where:
    - base_score = 100 (fully ready)
    - constraint_penalty = severity × probability × time_proximity
    - risk_penalty = impact × probability
    """
    
    def calculate_area_score(
        self, 
        area: FunctionalArea,
        constraints: list[CapacityConstraint],
        risks: list[RiskIndicator],
        growth_signals: list[GrowthSignal]
    ) -> ReadinessScore:
        """Calculate readiness score for a functional area."""
        
        base_score = 100.0
        
        # Constraint penalties
        constraint_penalty = sum(
            self._constraint_severity(c) * c.breach_probability * self._time_proximity(c)
            for c in constraints
        )
        
        # Risk penalties  
        risk_penalty = sum(
            r.impact_score * r.probability * self._risk_severity_multiplier(r.risk_level)
            for r in risks
        )
        
        # Growth signal amplifier (more aggressive growth = higher penalties)
        growth_multiplier = self._growth_intensity(growth_signals, area)
        
        final_score = max(0, base_score - (constraint_penalty + risk_penalty) * growth_multiplier)
        
        return ReadinessScore(
            functional_area=area,
            score=round(final_score, 1),
            constraints=[c.id for c in constraints],
            risks=[r.id for r in risks],
            trend=self._calculate_trend(area),
            assessed_at=datetime.utcnow()
        )
    
    def _constraint_severity(self, constraint: CapacityConstraint) -> float:
        """Map constraint type to severity weight."""
        severity_map = {
            ConstraintType.CAPACITY: 15.0,
            ConstraintType.DEPENDENCY: 12.0,
            ConstraintType.GOVERNANCE: 8.0,
            ConstraintType.FINANCIAL: 20.0,
            ConstraintType.TALENT: 10.0,
            ConstraintType.TIMELINE: 5.0,
        }
        return severity_map.get(constraint.constraint_type, 10.0)
    
    def _time_proximity(self, constraint: CapacityConstraint) -> float:
        """
        Penalties increase as breach date approaches.
        Returns multiplier: 0.5 (>12mo) to 2.0 (<1mo)
        """
        if not constraint.projected_breach_date:
            return 1.0
        
        days_until = (constraint.projected_breach_date - datetime.utcnow()).days
        
        if days_until < 30:
            return 2.0
        elif days_until < 90:
            return 1.5
        elif days_until < 180:
            return 1.0
        elif days_until < 365:
            return 0.75
        else:
            return 0.5
    
    def _risk_severity_multiplier(self, level: RiskLevel) -> float:
        """Map risk level to multiplier."""
        return {
            RiskLevel.LOW: 0.5,
            RiskLevel.MEDIUM: 1.0,
            RiskLevel.HIGH: 1.5,
            RiskLevel.CRITICAL: 2.5,
        }.get(level, 1.0)
    
    def _growth_intensity(
        self, 
        signals: list[GrowthSignal], 
        area: FunctionalArea
    ) -> float:
        """
        Calculate growth intensity multiplier.
        Aggressive growth plans amplify constraint/risk penalties.
        """
        relevant_signals = [s for s in signals if area in s.affected_areas]
        
        if not relevant_signals:
            return 1.0
        
        # Average magnitude of growth signals
        avg_magnitude = sum(s.magnitude for s in relevant_signals) / len(relevant_signals)
        
        # Convert to multiplier: 0% growth = 1.0, 100% growth = 1.5, 200%+ = 2.0
        return min(2.0, 1.0 + (avg_magnitude / 200))
```

### 5.4 Calibration & Validation

ScaleScore ships with explicit validation and calibration guardrails:

- **Deterministic tests:** Scoring behavior is validated against fixed scenarios (e.g., >80% utilization yields non-trivial penalties).
- **Configurable weights:** Severity weights and multipliers are stored in a configuration object to enable tuning without code changes.
- **Backtesting (future):** Support replaying historical snapshots to validate whether known failures would have been predicted.

### 5.5 Explainability

Every readiness score should be explainable at the factor level:

- **Contribution breakdown:** List of penalties with source entities and magnitude.
- **Evidence links:** References to growth signals and constraints that drove each penalty.
- **Narrative summary:** Human-readable “why” statements to surface in the UI.

### 5.3 Bottleneck Detection

```python
# src/scalescore/scoring/bottleneck_detector.py

class BottleneckDetector:
    """
    Identifies and prioritizes scaling bottlenecks.
    
    Uses a dependency graph to find:
    1. Direct capacity constraints
    2. Cascade effects (A depends on B, B is constrained)
    3. Concentration risks (too many things depend on one entity)
    """
    
    def detect_bottlenecks(
        self,
        entities: list[BaseEntity],
        growth_signals: list[GrowthSignal]
    ) -> list[CapacityConstraint]:
        """Analyze entities against growth signals to find bottlenecks."""
        
        constraints = []
        
        # Phase 1: Direct capacity analysis
        for entity in entities:
            if hasattr(entity, 'capacity_current') and hasattr(entity, 'capacity_max'):
                constraint = self._analyze_capacity(entity, growth_signals)
                if constraint:
                    constraints.append(constraint)
        
        # Phase 2: Dependency cascade analysis
        dependency_graph = self._build_dependency_graph(entities)
        cascade_constraints = self._analyze_cascades(dependency_graph, constraints)
        constraints.extend(cascade_constraints)
        
        # Phase 3: Concentration risk analysis
        concentration_risks = self._analyze_concentration(dependency_graph)
        constraints.extend(concentration_risks)
        
        return constraints
    
    def _analyze_capacity(
        self, 
        entity: BaseEntity, 
        signals: list[GrowthSignal]
    ) -> Optional[CapacityConstraint]:
        """Check if entity capacity will be exceeded given growth signals."""
        
        current = entity.capacity_current
        max_cap = entity.capacity_max
        
        if not current or not max_cap:
            return None
        
        utilization = current / max_cap
        
        # Project future utilization based on growth signals
        projected_growth = self._project_growth(entity, signals)
        projected_utilization = (current * (1 + projected_growth)) / max_cap
        
        if projected_utilization > 0.8:  # 80% threshold
            breach_probability = min(1.0, (projected_utilization - 0.8) / 0.2)
            
            return CapacityConstraint(
                id=f"cap_{entity.id}",
                entity_id=entity.id,
                entity_type=entity.type,
                constraint_type=ConstraintType.CAPACITY,
                current_utilization=utilization,
                projected_breach_date=self._estimate_breach_date(
                    current, max_cap, projected_growth
                ),
                breach_probability=breach_probability,
                mitigation_options=self._suggest_mitigations(entity),
            )
        
        return None
```

---

## 6. Recommendation Engine

### 6.1 Recommendation Types

```python
# src/scalescore/scoring/recommender.py

class RecommendationType(str, Enum):
    EXPAND_CAPACITY = "expand_capacity"
    ADD_REDUNDANCY = "add_redundancy"
    ACCELERATE_HIRING = "accelerate_hiring"
    DEFER_GROWTH = "defer_growth"
    REPLACE_SYSTEM = "replace_system"
    RENEGOTIATE_CONTRACT = "renegotiate_contract"
    ADD_GOVERNANCE = "add_governance"
    CREATE_CONTINGENCY = "create_contingency"


class Recommendation(BaseModel):
    id: str
    type: RecommendationType
    title: str
    description: str
    target_entity_id: str
    addresses_risks: list[str]  # risk_ids
    addresses_constraints: list[str]  # constraint_ids
    effort: str  # low, medium, high
    impact: str  # low, medium, high
    estimated_cost: Optional[float] = None
    estimated_time_days: Optional[int] = None
    priority_score: float = 0.0  # Calculated: impact / effort
```

### 6.2 Recommendation Logic

The recommendation engine uses pattern matching based on constraint types and historical playbooks:

| Constraint Pattern | Recommendation |
|--------------------|----------------|
| System at >80% capacity | Expand capacity OR replace with scalable alternative |
| Single vendor dependency (critical) | Add redundancy or negotiate SLA guarantees |
| Hiring plan > facility capacity | Secure additional real estate OR enable remote |
| Governance gap + compliance requirement | Implement controls framework |
| Financial runway < growth timeline | Raise capital OR defer growth plan |

---

## 7. API Design

### 7.1 REST Endpoints

The API implementation is in:
- `src/scalescore/api/main.py`
- `src/scalescore/api/v1/auth.py`

Authentication uses Bearer JWTs, with API key support via `X-API-Key` for service-to-service use cases.

**Authentication (`/api/v1/auth`)**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/login` | User login, returns access + refresh tokens |
| `POST` | `/signup` | Create user in auth store |
| `POST` | `/refresh` | Rotate refresh token, issue new access token |
| `POST` | `/logout` | Revoke refresh token (when provided) |
| `GET` | `/me` | Current user profile |
| `POST` | `/api-keys` | Create API key for current user |
| `GET` | `/api-keys` | List API keys for current user |
| `DELETE` | `/api-keys/{key_id}` | Revoke API key |

**Assessment + Analytics**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/assessments` | Run assessment from `dataset_path` (development only) |
| `POST` | `/api/v1/assessments/upload` | Run assessment from uploaded CSV bundle |
| `GET` | `/api/v1/assessments` | List stored assessments (paginated) |
| `GET` | `/api/v1/assessments/{assessment_id}` | Retrieve stored assessment |
| `GET` | `/api/v1/assessments/{assessment_id}/export/pdf` | Export assessment as PDF |
| `GET` | `/api/v1/scores/{org_id}/history` | Score history + 7d/30d/90d trends + comparison |

**Entity Management**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/organizations` | Create organization |
| `GET` | `/api/v1/organizations` | List organizations |
| `GET` | `/api/v1/organizations/{org_id}` | Get organization |
| `PUT` | `/api/v1/organizations/{org_id}` | Update organization |
| `DELETE` | `/api/v1/organizations/{org_id}` | Delete organization |
| `POST` | `/api/v1/entities/{entity_type}` | Create entity (team/system/vendor/facility) |
| `GET` | `/api/v1/entities/{entity_type}` | List entities by type |
| `GET` | `/api/v1/entities/{entity_type}/{entity_id}` | Get entity by ID |
| `PUT` | `/api/v1/entities/{entity_type}/{entity_id}` | Update entity |
| `DELETE` | `/api/v1/entities/{entity_type}/{entity_id}` | Delete entity |

**Import + Integration + Health**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/import/csv` | Import entity records from CSV |
| `POST` | `/api/v1/webhooks/opsorchestra` | Receive OpsOrchestra entity events |
| `GET` | `/api/v1/health` | Service health/version |

### 7.2 Data Import Specifications (CSV Contracts)

MVP ingestion supports CSV files with strict headers and required fields. Optional fields may be blank.

**organizations.csv**
```csv
id,name,headcount_current,revenue_current,burn_rate_monthly,runway_months
org_acme,AcmeTech,150,25000000,1200000,18
```

**teams.csv**
```csv
id,org_id,name,function,headcount_current,parent_team_id,manager_id
team_eng,org_acme,Engineering,engineering,60,,mgr_1
```

**systems.csv**
```csv
id,org_id,name,system_type,capacity_current,capacity_max,capacity_unit,is_critical,dependencies
sys_crm,org_acme,Salesforce,crm,650,1000,users,true,
```

**vendors.csv**
```csv
id,org_id,name,vendor_type,annual_cost,is_critical,alternatives
ven_cloud,org_acme,AWS,saas,1200000,true,Azure|GCP
```

**facilities.csv**
```csv
id,org_id,name,facility_type,location,capacity_seats,capacity_used,lease_end_date
fac_hq,org_acme,HQ,office,San Francisco,180,150,2027-06-30
```

**growth_signals.csv**
```csv
id,org_id,signal_type,title,target_date,magnitude,magnitude_type,confidence,affected_areas
sig_hc,org_acme,headcount_plan,Double headcount,2026-12-31,100,percentage,0.8,engineering|sales|operations
```

### 7.3 OpsOrchestra Integration API

Current integration surface includes a webhook ingestion endpoint:

- `POST /api/v1/integrations/opsorchestra/pull`
- `POST /api/v1/webhooks/opsorchestra`
- `POST /api/v1/assessments/{assessment_id}/sync/opsorchestra`

Supported event types:
- `entity.created`
- `entity.updated`
- `entity.deleted`

Security model:
- Optional `X-Webhook-Secret` header validation.
- In production, the shared secret must be configured (`INTEGRATION_OPSORCHESTRA_WEBHOOK_SECRET`).

---

## 8. User Interface (MVP)

### 8.1 MVP User Interface Requirements (Streamlit)

The MVP Streamlit experience is defined by four core views:

1. **Onboarding Wizard**
   - Upload CSV files with validation feedback (pass/fail + missing columns).
   - “Run Assessment” action to trigger scoring.
2. **Executive Dashboard**
   - Overall readiness score (gauge or metric).
   - Functional area cards with score, grade, and trend.
   - Critical risks ticker (top 3).
3. **Deep Dive View**
   - Select a functional area to see constraints and risks.
   - Capacity vs demand chart (projected utilization vs thresholds).
   - Constraint table with breach date and probability.
4. **Recommendations Panel**
   - Prioritized list of recommendations with effort/impact tags.
   - Expandable details for rationale and mitigation steps.

### 8.2 Key Visualizations

1. **Readiness Radar** — Polar chart showing scores by functional area
2. **Risk Heat Map** — Matrix of risk level × functional area
3. **Bottleneck Timeline** — Gantt-style view of when constraints hit
4. **Dependency Graph** — Network visualization of entity dependencies
5. **Score Trend** — Line chart of scores over time

---

## 9. Implementation Roadmap

The authoritative, continuously updated roadmap lives in `docs/ROADMAP.md`.

Current snapshot (February 2026):
- Phase 1 MVP foundation: complete.
- Phase 2 platform maturity: substantially complete (auth, CRUD, trend analytics, summaries, PDF export, webhook ingestion).
- Current focus: Phase 3 scale and integration (OpsOrchestra connector, async assessment execution, expanded scoring pillars).

---

## 10. Success Metrics

### For Job Hunting (Demo Readiness)
- [ ] Complete assessment runs in <30 seconds
- [ ] Produces actionable output from demo dataset
- [ ] Compelling 10-minute walkthrough possible
- [ ] Clear OpsOrchestra integration story

### For Business (If Pursued)
- [ ] 3+ design partners actively using
- [ ] Documented ROI from at least 1 partner
- [ ] Clear pricing model validated
- [ ] Technical infrastructure production-ready

---

## 11. Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Language** | Python 3.11+ | Consistency with OpsOrchestra, ML ecosystem |
| **API Framework** | FastAPI | Async, OpenAPI docs, Pydantic integration |
| **Models** | Pydantic v2 | OpsOrchestra compatibility, validation |
| **Database** | SQLite (dev) / Postgres (prod) | Simple start, scale later |
| **Graph Storage** | NetworkX (MVP) / Neo4j (scale) | Dependency analysis needs |
| **UI (MVP)** | Streamlit | Rapid prototyping, data focus |
| **UI (v2)** | React + Recharts | Production-ready dashboard |

---

## 12. Open Questions

1. **Scoring weights** — Should weights be configurable per org, or fixed heuristics?
2. **Historical data** — How much history is needed for trend analysis?
3. **Benchmark data** — Can we incorporate industry benchmarks for comparison?
4. **Privacy** — How to handle sensitive org data (headcount, financials)?
5. **Real-time vs batch** — Should scoring be continuous or on-demand?
6. **Storage strategy** — Do we persist reports in relational tables or as JSON snapshots?
7. **Auth model** — Standalone JWT now vs OAuth2/SSO later: confirm MVP scope.

---

## Appendix A: Demo Dataset

For demonstrations, ScaleScore includes a synthetic dataset based on a fictional Series B startup ("AcmeTech") with:

- 150 employees across 8 teams
- 12 core systems (CRM, HRIS, ERP, etc.)
- 8 critical vendors
- 3 facilities (HQ, remote hub, warehouse)
- Growth plan: 2x headcount in 12 months

This dataset is pre-loaded with realistic constraints and risks for demo purposes.

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **Readiness Score** | 0-100 measure of preparedness for planned growth |
| **Capacity Constraint** | A limit that could block scaling if not addressed |
| **Risk Indicator** | A specific identified risk with probability and impact |
| **Growth Signal** | A planned change that drives capacity requirements |
| **Bottleneck** | A constraint that would cause cascading failures |
| **Functional Area** | Organizational domain (Engineering, Sales, Ops, etc.) |
