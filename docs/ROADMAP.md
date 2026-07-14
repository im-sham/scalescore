# Proofhouse Readiness Roadmap

> **Last Updated**: April 26, 2026
> **Status**: Active Development  
> **Owner**: Product & Engineering

---

## Vision

Proofhouse Readiness is the workflow-first scoring and diagnostic layer for **AI-enabled operational readiness**.

The current technical service remains `scalescore` until a later rename wave. Product and roadmap language should use Readiness.

The product is no longer optimized around a broad "scaling companies" category. It is optimized around a more precise question:

**Is this workflow ready to scale with AI without creating fragility, trust failures, or governance gaps?**

### North Star Metrics

- Workflow assessment completion in `< 30 seconds` for compatibility-mode runs
- Actionable remediation output in every workflow report
- Clear workflow-to-org rollup for AI operational readiness
- Proofhouse operators and suite users can identify which workflows are ready to scale with AI and act on the highest-priority trust gaps

---

## Strategic Guardrails

- Keep Readiness primarily a Proofhouse suite capability
- Require an explicit product decision and independent product rationale for any standalone product surface. Keep partnership, pilot, live-client, and GTM status in a separate non-product lane whose status cannot change Readiness product status or readiness; partner/customer activation remains separately frozen
- Preserve current org-level API and CSV compatibility while the workflow-first contract is introduced
- Do **not** expand into generic financial, customer, or marketing benchmarking unless it directly improves AI workflow readiness scoring
- Keep legacy `OpsOrchestra`, `Mila`, and `ScaleScore` naming only where required for technical backward compatibility
- Treat Operational Learning as a suitability lens; Governance remains the approval plane for rights, redaction, promotion, and export decisions
- Treat design-partner, advisor, consulting, customer-discovery, partnership, pilot, and live-client evidence as informative and non-authoritative. It cannot create, prioritize, block, complete, waive, accept, release, or authorize product roadmap work or any safety, security, privacy, legal, data, hosted, operational, release, or external-claim gate. Only an explicitly promoted sanitized, generalized problem with independent product rationale may enter product strategy, and that promotion requires product-owner acceptance

---

## Current State

### Already Implemented

| Area | Status |
|------|--------|
| Core models, scoring, bottleneck detection, recommendations | ✅ Complete |
| Assessment persistence and report retrieval | ✅ Complete |
| FastAPI auth, API keys, org/entity CRUD, trend history | ✅ Complete |
| Async assessments and scheduling slice | ✅ Complete |
| Staging validation gate and security baseline | ✅ Complete |
| Workflow-first report enrichment (`workflow_context`, pillar scores, trust gaps, rollup metadata) | ✅ Initial additive slice complete |
| Workflow-first HTTP submission across sync, async, and scheduled paths | ✅ Initial additive slice complete |

### Compatibility Commitments

- Existing org-level assessment flow remains supported
- Existing async, scheduling, and staging validation flows remain supported
- Existing HTTP endpoints remain supported
- Workflow-first becomes the canonical product narrative without breaking the current runtime

---

## 90-Day Plan

### Days 1-14: Strategy Reset

**Goal:** Align portfolio and product materials around the same product.

| Item | Status |
|------|--------|
| USMI repositioning brief | ✅ Implemented |
| Mission Control and product rollup updates | ✅ Implemented |
| README rewrite | ✅ Implemented |
| Technical spec rewrite | ✅ Implemented |
| API and operator docs updated for workflow-first compatibility narrative | ✅ Implemented |

### Days 15-45: Product Contract Reset

**Goal:** Make workflow-first assessment the canonical contract while preserving org-level compatibility.

| Item | Status |
|------|--------|
| Define workflow assessment metadata object | ✅ Initial additive contract implemented |
| Define readiness pillars and report outputs | ✅ Initial additive contract implemented |
| Derive org rollup metadata from workflow reports | ✅ Initial additive contract implemented |
| Introduce HTTP submission contract for workflow assessment targets | ✅ Initial additive contract implemented |
| Map current org-level signals to workflow-first pillar logic | 🔄 Next |
| Identify missing inputs required for stronger workflow scoring | 🔄 Next |

### Days 46-90: Implementation Preparation

**Goal:** Connect Readiness to real Workflow Context data and package operator-facing diagnostics.

| Item | Status |
|------|--------|
| Minimal Workflow Context integration path | ✅ Initial direct integration implemented |
| Workflow Context-native submission contract | ✅ Initial direct contract implemented |
| Operational Learning suitability lens | ✅ Initial additive slice implemented |
| Regulated document-operations suitability profile | ✅ Initial additive slice implemented |
| Operator-facing diagnostic/report surface | 🔄 Planned |
| Compatibility guardrails for org-level flows | ✅ Preserved in current additive rollout |

---

## Product Contract Priorities

### Canonical Assessment Unit

Readiness is now `workflow / use-case first`.

Examples:

- Support triage
- Finance close automation
- Vendor onboarding
- Knowledge intake

Organization-level readiness remains important, but becomes a rollup derived from workflow assessments.

### Readiness Pillars

1. **Workflow stability**  
   Repeatability, exception rate, process clarity, reversibility.
2. **System and dependency resilience**  
   Capacity headroom, vendor concentration, cascade risk, critical integrations.
3. **Human oversight and ownership**  
   Named owner, escalation path, override rights, fallback mode.
4. **Control and evidence readiness**  
   Approval traceability, logging, audit evidence, decision records.
5. **Automation fit and blast radius**  
   Task suitability, error tolerance, impact scope, containment ability.

---

## Public Interface Direction

### Phase 1

- No breaking HTTP API changes
- No breaking CSV/demo changes
- Additive report-model support for workflow context and rollup metadata

### Phase 2

- Introduce first-class workflow assessment submission contract
- Add a direct Workflow Context submission path that does not require dataset CSVs
- Return workflow readiness score, pillar breakdown, trust gaps, and org rollup data from relevant report endpoints
- Return optional Operational Learning suitability when supplied with governance dependency inputs
- Return document-operations suitability when supplied with the flagship profile derived from Workflow Context refs/snapshots
- Preserve org-level assessments in compatibility mode during transition

---

## Success Criteria

- Portfolio and product docs describe the same product in the same language
- A reader can distinguish Readiness from Workflow Context, Governance, and Forge immediately
- A sample workflow assessment can output:
  - workflow readiness score
  - pillar breakdown
  - top trust gaps
  - prioritized remediation actions
  - optional Operational Learning suitability status
  - compact `AssessmentRef` for downstream Proofhouse consumers
- Multiple workflow assessments can be rolled up into an organization-level readiness view
- Operator-facing diagnostic and report capabilities support suite workflows; any standalone product surface follows the strategic guardrails above

---

## Explicitly Not Doing

- Repositioning Readiness as a generic operations benchmarking platform
- Making Readiness responsible for workflow truth, runtime policy enforcement, use approvals, export control, or compliance operations
- Removing the current org-level surface before workflow-first submission paths are ready
