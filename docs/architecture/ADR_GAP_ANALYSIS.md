# Chief Architect Assessment: ADR Gap Analysis

> **Date**: January 2026  
> **Author**: Chief Architect  
> **Purpose**: Identify and prioritize architectural decisions requiring formal documentation
>
> **Historical note (February 2026):** This document captures a pre-implementation snapshot.
> Several items listed as missing (for example auth, logging, config, error handling) have since
> been implemented. Use `docs/ROADMAP.md` for current execution status.

---

## Executive Summary

This assessment identifies **15 additional architectural decisions** that should be documented to ensure ScaleScore is built for scale, with graceful architecture, and security-first principles. These decisions fall into three categories:

1. **Decisions Made But Undocumented** - Already in code, need formal ADRs
2. **Imminent Decisions** - Must be decided before next phase
3. **Strategic Decisions** - Should be planned now to avoid rework

---

## Assessment Methodology

Analyzed the codebase for:
- Implicit architectural patterns in use
- Technology choices without documented rationale
- Security-sensitive areas lacking formal decisions
- Scale-impacting decisions that could require rework
- Cross-cutting concerns without established patterns

---

## Category 1: Decisions Made But Undocumented

These decisions are already implemented in code but lack formal ADRs. This is a documentation debt that should be resolved immediately.

### ADR-0007: Error Handling Strategy (HIGH PRIORITY)

**Current State:**
- Using `ValueError` for validation errors throughout
- No structured error types or hierarchy
- No consistent error response format in API
- No error codes for client handling

**Evidence:**
```python
# csv_connector.py - 7 instances of ValueError
raise ValueError(f"Missing required columns: {', '.join(missing)}")
raise ValueError(f"Missing required value for {key}")

# assessment.py
raise ValueError("At least one organization is required")
raise ValueError("Assessment supports a single organization")
```

**Risk if Undocumented:**
- Inconsistent error handling across modules
- Poor API error responses for clients
- Difficult debugging without error codes
- Security risk: may leak internal details

**Recommendation:** Document and implement structured error hierarchy with domain-specific exceptions.

---

### ADR-0008: API Versioning Strategy (HIGH PRIORITY)

**Current State:**
- Using URL path versioning (`/api/v1/...`)
- No documented strategy for breaking changes
- No deprecation policy
- Assessment version separate from API version

**Evidence:**
```python
# api/main.py
@app.post("/api/v1/assessments", response_model=ScaleScoreReport)
@app.get("/api/v1/health")
return {"status": "healthy", "version": "0.1.0"}
```

**Risk if Undocumented:**
- Breaking changes without migration path
- Client confusion about compatibility
- OpsOrchestra integration instability

**Recommendation:** Formalize versioning strategy with deprecation timeline (6 months minimum).

---

### ADR-0009: Configuration Management (HIGH PRIORITY)

**Current State:**
- Dataclass-based configs for internal components (good)
- No centralized application configuration
- No environment-based configuration
- No secrets management pattern

**Evidence:**
```python
# scoring/engine.py
@dataclass(frozen=True)
class ScoringConfig:
    base_score: float = 100.0
    # ... hardcoded defaults

# api/main.py - No configuration loading
app = FastAPI(title="ScaleScore API", version="0.1.0")  # Hardcoded
```

**Risk if Undocumented:**
- Environment-specific values hardcoded
- Secrets potentially committed to code
- Difficult deployment across environments
- Configuration sprawl

**Recommendation:** Implement pydantic-settings with environment variable support.

---

### ADR-0014: Dependency Graph Engine (NetworkX) (MEDIUM PRIORITY)

**Current State:**
- NetworkX listed in dependencies but usage is implicit
- Dependency graph built in bottleneck_detector.py
- No formal decision on graph storage vs. in-memory

**Evidence:**
```toml
# pyproject.toml
"networkx>=3.0",
```
```python
# bottleneck_detector.py - Custom DependencyNode dataclass instead of NetworkX
@dataclass
class DependencyNode:
    entity_id: str
    dependents: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
```

**Risk if Undocumented:**
- Unclear when to use NetworkX vs. custom structures
- Scale implications for large dependency graphs
- No persistence strategy for graphs

**Recommendation:** Document graph engine choice and usage patterns.

---

### ADR-0015: Report Immutability and Versioning (MEDIUM PRIORITY)

**Current State:**
- Reports have `report_version` field
- Assessment scores have `assessment_version` field
- No formal versioning strategy documented

**Evidence:**
```python
# models/scaling.py
class ReadinessScore(BaseModel):
    assessment_version: str = "1.0"

class ScaleScoreReport(BaseModel):
    report_version: str = "1.0"
```

**Risk if Undocumented:**
- Schema changes break historical report parsing
- No migration strategy for version changes
- Client compatibility issues

**Recommendation:** Document versioning strategy and backward compatibility rules.

---

## Category 2: Imminent Decisions (Must Decide Before Phase 2)

These decisions must be made before implementing Phase 2 features.

### ADR-0010: Structured Logging and Observability (HIGH PRIORITY)

**Current State:**
- No logging implementation
- No metrics collection
- No tracing
- No correlation IDs

**Evidence:** Zero matches for `logging`, `logger`, `log.` in codebase.

**Why Critical:**
- Cannot debug production issues
- Cannot measure performance
- SOC2 requires audit trails
- Security incident detection impossible

**Recommendation:** Implement structured JSON logging with OpenTelemetry for tracing.

---

### ADR-0011: Authentication and Authorization Strategy (HIGH PRIORITY)

**Current State:**
- No authentication
- All API endpoints public
- Multi-tenancy defined but not enforced

**Evidence:** Zero matches for `jwt`, `auth`, `token` in source code.

**Why Critical:**
- Complete security gap
- Tenant isolation not enforceable
- Cannot proceed to production
- OpsOrchestra integration requires auth

**Recommendation:** JWT with RS256 signing, refresh tokens, and RBAC.

---

### ADR-0012: Background Job Processing (MEDIUM PRIORITY)

**Current State:**
- All processing synchronous
- Large assessments block API thread
- No scheduled job capability

**Evidence:**
```python
# assessment.py - Synchronous processing
def run_assessment_from_csv(directory: str | Path) -> ScaleScoreReport:
    connector = CSVConnector()
    data = connector.load_all(directory)  # Blocking
    return run_assessment(...)  # Blocking
```

**Why Critical:**
- API timeouts for large organizations
- Cannot implement scheduled assessments
- Cannot implement webhooks without async

**Recommendation:** Celery with Redis broker for async processing.

---

## Category 3: Strategic Decisions (Plan Now, Implement Later)

These decisions should be documented now to guide future implementation.

### ADR-0013: Testing Strategy (MEDIUM PRIORITY)

**Current State:**
- pytest with basic fixtures
- ~60% coverage estimated
- No integration test strategy
- No performance test strategy

**Evidence:**
```python
# test_scoring_engine.py - Unit test pattern exists
def test_score_penalizes_constraints() -> None:
    engine = ScoringEngine()
    constraint = CapacityConstraint(...)
    result = engine.calculate_area_score(...)
    assert result.score < 100
```

**Why Important:**
- Establish coverage requirements
- Define test pyramid (unit/integration/e2e)
- Performance regression prevention

**Recommendation:** Document test pyramid, coverage requirements, and performance baselines.

---

### ADR-0016: OpsOrchestra Integration Pattern (MEDIUM PRIORITY)

**Current State:**
- Integration mentioned in docs
- Optional dependency defined
- No integration code exists

**Evidence:**
```toml
# pyproject.toml
opsorchestra = [
    "opsorchestra>=0.1.0",
]
```

**Why Important:**
- Major integration point
- Affects data model decisions
- Impacts authentication strategy

**Recommendation:** Document integration patterns before Phase 3.

---

### ADR-0017: Deployment and Infrastructure (LOW PRIORITY NOW)

**Current State:**
- No Dockerfile
- No CI/CD configuration
- No infrastructure-as-code

**Why Important:**
- Production deployment blocked
- Cannot demonstrate in cloud environment
- No blue-green deployment capability

**Recommendation:** Document containerization and deployment strategy before Phase 4.

---

### ADR-0018: Caching Strategy (LOW PRIORITY NOW)

**Current State:**
- No caching implemented
- No cache dependencies

**Why Important:**
- Performance at scale
- Reduce database load
- Session storage for auth

**Recommendation:** Document Redis caching strategy when implementing auth.

---

## Priority Matrix

| ADR | Priority | Effort | Impact | Phase |
|-----|----------|--------|--------|-------|
| ADR-0007 Error Handling | HIGH | Medium | High | 1 |
| ADR-0008 API Versioning | HIGH | Low | High | 1 |
| ADR-0009 Configuration | HIGH | Medium | High | 1 |
| ADR-0010 Observability | HIGH | Medium | High | 2 |
| ADR-0011 Authentication | HIGH | High | Critical | 2 |
| ADR-0012 Background Jobs | MEDIUM | High | Medium | 3 |
| ADR-0013 Testing | MEDIUM | Low | Medium | 1 |
| ADR-0014 NetworkX | MEDIUM | Low | Low | 1 |
| ADR-0015 Report Versioning | MEDIUM | Low | Medium | 1 |
| ADR-0016 OpsOrch Integration | MEDIUM | Medium | High | 3 |
| ADR-0017 Deployment | LOW | High | High | 4 |
| ADR-0018 Caching | LOW | Medium | Medium | 3 |

---

## Immediate Action Items

### This Sprint (Phase 1 Completion)
1. Create ADR-0007 through ADR-0009 (error handling, versioning, configuration)
2. Create ADR-0013 through ADR-0015 (testing, NetworkX, report versioning)
3. Update ADR index

### Next Sprint (Phase 2 Start)
4. Create ADR-0010 and ADR-0011 (observability, authentication)
5. Begin implementation of logging infrastructure
6. Begin authentication design

### Future Sprints
7. Create remaining ADRs as features approach

---

## Conclusion

The ScaleScore codebase has solid foundational decisions (documented in ADR-0001 through ADR-0006) but lacks formal documentation for several cross-cutting concerns. The most critical gaps are:

1. **Error Handling** - No structured approach
2. **Observability** - Cannot operate in production
3. **Authentication** - Complete security gap
4. **Configuration** - Hardcoded values throughout

Addressing these gaps will ensure ScaleScore meets the three guiding principles:
- **Build for Scale**: Proper configuration and background processing
- **Graceful Architecture**: Consistent error handling and patterns
- **Security-First**: Authentication, observability, and audit logging

---

*This assessment should be reviewed quarterly as the codebase evolves.*
