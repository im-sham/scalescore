# ScaleScore Roadmap

> **Last Updated**: February 2026  
> **Status**: Active Development  
> **Owner**: Product & Engineering

---

## Vision

ScaleScore will be the definitive operational readiness platform for scaling companies. We predict where organizations will break before they break, enabling proactive capacity planning and risk mitigation.

**North Star Metrics:**
- Assessment completion in < 30 seconds
- Actionable recommendations in every report
- 90%+ accuracy on bottleneck predictions (validated post-hoc)

---

## Guiding Principles for Implementation

These principles apply to ALL roadmap items:

### Build for Scale
- Every feature designed for 100x data volume
- Multi-tenancy is foundational, not retrofitted
- Database queries optimized from day one
- Background processing for any operation > 5 seconds

### Graceful Architecture  
- New code follows established patterns (see ARCHITECTURE.md)
- Refactoring happens during feature work, not as tech debt sprints
- Interface-first design for all new components
- 80%+ test coverage for new code

### Security-First
- Data classification required for all new fields
- Audit logging for state-changing operations
- No secrets in code, ever
- Security review for all external integrations

---

## Release Strategy

| Release Type | Cadence | Scope |
|--------------|---------|-------|
| **Major (1.0, 2.0)** | Quarterly | New pillars, major features, breaking changes |
| **Minor (1.1, 1.2)** | Bi-weekly | New features, enhancements |
| **Patch (1.1.1)** | As needed | Bug fixes, security patches |

---

## Roadmap Phases

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SCALESCORE ROADMAP                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Q1 2026                Q2 2026                Q3 2026           Q4 2026    │
│  ─────────              ─────────              ─────────          ────────  │
│                                                                              │
│  ┌──────────┐          ┌──────────┐          ┌──────────┐      ┌─────────┐ │
│  │ Phase 1  │─────────▶│ Phase 2  │─────────▶│ Phase 3  │─────▶│ Phase 4 │ │
│  │   MVP    │          │ Platform │          │ Scale    │      │Enterprise│ │
│  │ v0.1-0.3 │          │ v0.4-0.6 │          │ v0.7-0.9 │      │  v1.0   │ │
│  └──────────┘          └──────────┘          └──────────┘      └─────────┘ │
│                                                                              │
│  • Core scoring         • Database            • OpsOrchestra    • SSO/SAML │
│  • CSV import           • Authentication      • Background jobs • Audit    │
│  • Basic API            • User management     • Additional      • Export   │
│  • Streamlit UI         • API completion        pillars         • SLA      │
│  • Demo dataset         • Trend analysis      • Benchmarks                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: MVP Foundation (v0.1 - v0.3)

**Timeline:** Weeks 1-4  
**Goal:** Demonstrate core value proposition with working assessment pipeline

### v0.1.0 - Core Engine (✅ COMPLETE)

| Item | Status | Description |
|------|--------|-------------|
| Pydantic models | ✅ Done | Core entities and scaling models |
| Scoring engine | ✅ Done | Constraint-based scoring algorithm |
| Bottleneck detector | ✅ Done | Capacity, cascade, concentration analysis |
| Recommendation engine | ✅ Done | Pattern-based recommendation generation |
| CSV connector | ✅ Done | Import all 6 entity types |

**Deliverable:** Can run assessment from CSV files programmatically

### v0.2.0 - API & UI (🔄 IN PROGRESS)

| Item | Status | Description | ADR |
|------|--------|-------------|-----|
| FastAPI basic endpoints | ✅ Done | Assessment and health endpoints | - |
| Streamlit dashboard | ✅ Done | Upload, dashboard, deep-dive views | - |
| Demo dataset | ✅ Done | AcmeTech sample data | - |
| API file upload | ✅ Done | Multi-file assessment endpoint | - |
| Error handling | ✅ Done | Structured domain + request validation responses | ADR-0007 |
| Request validation | ✅ Done | Pydantic request models and standardized 422 payloads | ADR-0007 |

**Deliverable:** Interactive demo via Streamlit + API

### v0.3.0 - Production Foundation

| Item | Status | Description | ADR |
|------|--------|-------------|-----|
| Database persistence | ✅ Done (MVP scope) | SQLite snapshot persistence for assessments | ADR-0006 |
| Repository pattern | 🔄 Partial | Repository implemented for assessment snapshots | ADR-0004 |
| Report storage | ✅ Done | Immutable assessment snapshots stored and retrievable by ID | ADR-0015 |
| Configuration management | ✅ Done | Environment-based config via `pydantic-settings` | ADR-0009 |
| Structured logging | ✅ Done | JSON/text structured logs with correlation IDs and redaction | ADR-0010 |
| Test infrastructure | ✅ Done | Pytest suite with unit/integration/e2e and strong coverage | ADR-0013 |

**Deliverable:** Persistent storage, production-ready foundation

### Phase 1 Success Criteria

- [x] End-to-end assessment runs in < 10 seconds for demo data
- [x] Reports persist and can be retrieved by ID
- [x] 70%+ test coverage on core modules
- [x] Compelling 10-minute demo walkthrough possible
- [x] No critical security vulnerabilities (dependency scan clean)

---

## Phase 2: Platform Maturity (v0.4 - v0.6)

**Timeline:** Weeks 5-10  
**Goal:** Production-ready platform with user management and history

### v0.4.0 - Authentication & Authorization

| Item | Description | Priority | ADR |
|------|-------------|----------|-----|
| JWT authentication | Token-based API auth | HIGH | ADR-0011 |
| API key support | Service-to-service auth | HIGH (✅ implemented) | - |
| User model | Basic user with org association | HIGH (✅ implemented) | - |
| Role-based access | Viewer / Analyst / Admin / Super Admin roles | MEDIUM | ADR-0011 |
| Session management | Token refresh + logout with SQLite-backed refresh token persistence | MEDIUM | ADR-0011 |

**Security Milestone:** Assessment endpoints and report retrieval/list/history endpoints protected, audit logging enabled

### v0.5.0 - API Completion

| Item | Description | Priority |
|------|-------------|----------|
| GET /assessments/{id} | Retrieve stored assessment | HIGH (✅ implemented) |
| GET /assessments | List assessments with pagination | HIGH (✅ implemented) |
| GET /scores/{org_id}/history | Score trend over time | HIGH (✅ implemented; baseline timeline) |
| Organization CRUD | Full entity management | MEDIUM (✅ implemented) |
| Entity CRUD | Manage teams, systems, etc. | MEDIUM (✅ implemented) |
| Webhook endpoints | OpsOrchestra integration prep | LOW |

### v0.6.0 - Analytics & Trends

| Item | Description | Priority |
|------|-------------|----------|
| Score history storage | Track scores over time | HIGH |
| Trend calculation | 7d, 30d, 90d trends | HIGH (✅ implemented) |
| Comparative analysis | Score vs. previous assessment | MEDIUM (✅ implemented) |
| Executive summary | Auto-generated narrative | MEDIUM |
| PDF export | Downloadable report | LOW |

### Phase 2 Success Criteria

- [x] User can sign up, authenticate, run assessments
- [x] Historical assessments queryable
- [x] Trend analysis shows score progression
- [ ] API documentation complete (OpenAPI)
- [ ] Security audit passed (OWASP top 10)

---

## Phase 3: Scale & Integration (v0.7 - v0.9)

**Timeline:** Weeks 11-16  
**Goal:** Enterprise features, OpsOrchestra integration, expanded coverage

### v0.7.0 - OpsOrchestra Integration

| Item | Description | Priority | ADR |
|------|-------------|----------|-----|
| OpsOrchestra connector | Pull entities from knowledge graph | HIGH | ADR-010 |
| Bidirectional sync | Push risks back to OpsOrchestra | MEDIUM | - |
| Webhook handler | React to entity changes | MEDIUM | - |
| Tenant context | Inherit auth from OpsOrchestra | HIGH | - |

### v0.8.0 - Background Processing

| Item | Description | Priority | ADR |
|------|-------------|----------|-----|
| Task queue | Celery + Redis infrastructure | HIGH | ADR-011 |
| Async assessments | Non-blocking for large orgs | HIGH | - |
| Scheduled assessments | Daily/weekly auto-run | MEDIUM | - |
| Progress tracking | Real-time assessment status | MEDIUM | - |

### v0.9.0 - Expanded Pillars

| Item | Description | Priority |
|------|-------------|----------|
| Financial pillar | Unit economics, CAC/LTV, burn multiple | HIGH |
| People pillar | Hiring velocity, attrition, manager ratio | HIGH |
| Customer pillar | NPS, churn, expansion metrics | MEDIUM |
| Industry benchmarks | Compare scores to peer group | MEDIUM |

### Phase 3 Success Criteria

- [ ] OpsOrchestra integration functional in staging
- [ ] Assessments complete async for orgs with 1000+ entities
- [ ] 8+ functional areas scored (up from 6)
- [ ] Benchmark comparison available for 3+ company stages

---

## Phase 4: Enterprise Ready (v1.0)

**Timeline:** Weeks 17-24  
**Goal:** SOC2-ready, enterprise features, production SLA

### v1.0.0 - Enterprise Features

| Item | Description | Priority | ADR |
|------|-------------|----------|-----|
| SSO/SAML | Enterprise identity integration | HIGH | ADR-012 |
| Advanced audit | Comprehensive audit log export | HIGH | - |
| Data retention | Configurable retention policies | HIGH | - |
| Rate limiting | API quota management | HIGH | - |
| Multi-region | Data residency options | MEDIUM | ADR-013 |

### Security & Compliance

| Item | Description | Priority |
|------|-------------|----------|
| SOC2 Type II prep | Control documentation | HIGH |
| Penetration testing | Third-party security audit | HIGH |
| Encryption at rest | Database encryption | HIGH |
| Secret management | Vault integration | MEDIUM |

### v1.0.0 Success Criteria

- [ ] SOC2 Type I certification achieved
- [ ] 99.9% uptime SLA achievable
- [ ] Enterprise customer pilot complete
- [ ] Comprehensive security documentation
- [ ] Production runbook complete

---

## Technical Debt Policy

### Prevention Over Cure

We prevent tech debt by:
1. **Designing before building** - ADRs for significant decisions
2. **Building incrementally** - Small, focused PRs
3. **Refactoring in context** - Fix related tech debt during feature work
4. **Maintaining test coverage** - New code requires tests

### Debt Classification

| Level | Definition | Action |
|-------|------------|--------|
| **Critical** | Blocks features or causes production issues | Fix immediately |
| **High** | Slows development significantly | Fix within 2 sprints |
| **Medium** | Causes friction but workaroundable | Fix when touching related code |
| **Low** | Nice to have improvements | Opportunistic fixing |

### Current Tech Debt Inventory

| Item | Level | Description | Target |
|------|-------|-------------|--------|
| Webhook endpoints pending | Medium | OpsOrchestra integration hooks not implemented yet | v0.5.1 |
| Executive summary generation | Medium | Narrative summary automation pending | v0.6.1 |
| PDF export pipeline | Medium | Report export endpoint not implemented | v0.6.1 |
| Filesystem `dataset_path` mode remains dev-only | Medium | Must stay disabled outside development | v0.4.1 |
| OpsOrchestra connector not implemented | Medium | Integration path defined but connector code pending | v0.7.0 |

---

## Milestones & Checkpoints

### Monthly Review Checkpoints

| Date | Milestone | Key Deliverables |
|------|-----------|------------------|
| Feb 2026 | MVP Foundation Complete | Persistent snapshots, secured assessment flow, demo-ready |
| Mar 2026 | Platform v0.5 | Durable auth store, API completion, trend analysis |
| Apr 2026 | Integration v0.7 | OpsOrchestra connected |
| May 2026 | Scale v0.9 | Async processing, expanded pillars |
| Jun 2026 | Enterprise v1.0 | SSO, SOC2 prep complete |

### Go/No-Go Criteria

Before advancing to next phase:
- [ ] All "HIGH" priority items complete
- [ ] Test coverage meets target (70%+ Phase 1, 80%+ Phase 2+)
- [ ] No critical or high security vulnerabilities
- [ ] Documentation updated
- [ ] Performance targets met

---

## Dependencies & Risks

### External Dependencies

| Dependency | Risk | Mitigation |
|------------|------|------------|
| OpsOrchestra API | Changes could break connector | Version-pinned client, adapter pattern |
| Auth provider (future) | Vendor lock-in | Abstract auth interface |
| Cloud provider | Cost, availability | Multi-cloud deployment option |

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Scoring accuracy | Medium | High | Validation with real data, calibration framework |
| Performance at scale | Low | High | Load testing, async architecture |
| Security breach | Low | Critical | Security-first design, audits, monitoring |

---

## Appendix: Feature Backlog

Features prioritized but not yet scheduled:

| Feature | Description | Phase Target |
|---------|-------------|--------------|
| Mobile-responsive UI | Dashboard works on mobile | Phase 3 |
| Slack integration | Assessment notifications | Phase 3 |
| Custom scoring weights | Org-specific weight configuration | Phase 2 |
| What-if scenarios | Simulate changes before making them | Phase 3 |
| AI recommendations | ML-powered action suggestions | Phase 4 |
| White-label support | Customer branding | Phase 4 |
| API rate analytics | Usage tracking and quotas | Phase 4 |
