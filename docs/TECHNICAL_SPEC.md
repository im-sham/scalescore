# ScaleScore Technical Specification

**Version:** 0.2.0  
**Author:** Shamim Rehman  
**Updated:** March 2026  
**Status:** Active specification

---

## Executive Summary

ScaleScore is the workflow-first scoring and diagnostic layer for **AI-enabled operational readiness**.

The product is designed to help operations leaders determine whether a specific workflow is ready to scale with AI without creating fragility, trust failures, or governance gaps. Organization-level readiness remains important, but is derived from workflow assessments rather than treated as the only primary object.

**Core value proposition:**  
Know which AI-enabled workflows are ready to scale, and what will break trust first.

---

## 1. Product Definition

### 1.1 Primary User

- COO / operations lead

### 1.2 Primary Use Cases

- assess whether a workflow is ready for more AI autonomy
- identify the trust gaps that block safe AI scale
- prioritize remediation before expanding automation
- roll workflow-level assessments into an organization-wide readiness view

### 1.3 Product Boundaries

| Product | Responsibility |
|---------|----------------|
| **Mila** | Workflow context, operating data, system of work |
| **ScaleScore** | Readiness scoring, trust-gap diagnosis, remediation prioritization |
| **Sentinel** | Runtime governance, control enforcement, compliance evidence |
| **Forge** | Failure-pattern input and scoring-model refinement |

**Boundary rule:** ScaleScore scores readiness and recommends remediation. It does not own runtime policy enforcement or compliance operations.

---

## 2. Canonical Assessment Unit

ScaleScore is now **workflow / use-case first**.

Examples:

- support triage
- finance close automation
- vendor onboarding
- knowledge intake

Organization-level scoring remains supported in compatibility mode. The long-term product model is:

1. assess individual AI-enabled workflows
2. score readiness across defined pillars
3. derive organization-level readiness from a portfolio of workflow assessments

---

## 3. Workflow Assessment Contract

### 3.1 Required Metadata

The workflow assessment object must include:

- `workflow_id`
- `name`
- `business_function`
- `owner`
- `ai_role`
- `systems_touched`
- `human_escalation_path`
- `control_requirements`
- `blast_radius`

### 3.2 Supporting Metadata

The initial additive contract also supports:

- `description`
- `fallback_mode`
- `override_rights`
- `error_tolerance`
- `reversibility`

### 3.3 Current Runtime Shape

The Python/report contract now supports:

- `workflow_context`
- `workflow_readiness_score`
- `workflow_readiness_grade`
- `workflow_pillar_scores`
- `top_trust_gaps`
- `prioritized_remediation_actions`
- `org_rollup`

Current HTTP API endpoints remain backward compatible and now support workflow submission across sync, async, and scheduled paths:

- `POST /api/v1/assessments/workflow` accepts `dataset_path` plus `workflow_context`
- `POST /api/v1/assessments/mila/workflow` accepts direct workflow metadata from Mila (`org_id`, `org_name`, `workflow_context`, optional baseline findings)
- `POST /api/v1/assessments/upload` accepts optional `workflow_context_json`
- `POST /api/v1/assessments/async/upload` accepts optional `workflow_context_json`
- `POST /api/v1/assessments/schedules/upload` accepts optional `workflow_context_json`

---

## 4. Readiness Pillars

ScaleScore workflow readiness is scored across five pillars:

### 4.1 Workflow Stability

Measures:

- process clarity
- repeatability
- reversibility
- known operational constraints
- exception pressure

### 4.2 System and Dependency Resilience

Measures:

- systems touched by the workflow
- critical dependency concentration
- cascade risk
- capacity headroom
- integration fragility

### 4.3 Human Oversight and Ownership

Measures:

- named owner
- escalation path
- fallback mode
- override rights
- human accountability

### 4.4 Control and Evidence Readiness

Measures:

- control requirements
- approval traceability
- evidence expectations
- decision logging
- governance-related findings

### 4.5 Automation Fit and Blast Radius

Measures:

- suitability for AI assistance
- error tolerance
- containment ability
- reversibility
- impact if the workflow fails

---

## 5. Report Contract

### 5.1 Compatibility Report

The existing organization report remains the compatibility baseline:

- overall score
- functional area scores
- constraints
- top risks
- recommendations
- executive summary

### 5.2 Workflow-First Additions

When workflow context is present, the report also includes:

- `assessment_mode = workflow`
- workflow readiness score and grade
- per-pillar scores and rationales
- top trust gaps
- prioritized remediation actions
- org rollup metadata

### 5.3 Executive Narrative

Workflow-scoped reports should explain:

- what workflow was assessed
- which AI role was evaluated
- where trust or readiness is weakest
- what the first remediation action should be
- how the workflow score contributes to the org rollup

---

## 6. Organization Rollup Logic

Organization readiness is derived from workflow reports, not defined separately.

The initial rollup contract includes:

- workflow count
- workflow IDs included
- average workflow score
- highest workflow score
- lowest workflow score
- total critical risks
- explanatory note describing the rollup method

The initial rollup method is a simple mean of workflow readiness scores. This is sufficient for the additive contract and can later evolve into weighted rollups by workflow criticality, blast radius, or business importance.

---

## 7. Compatibility and Migration Rules

- No breaking API change in this phase
- No breaking CSV/demo change in this phase
- Org-level assessments remain supported during the workflow-first transition
- Async, scheduling, persistence, and staging validation flows remain supported
- Legacy `OpsOrchestra` naming remains only where needed for existing technical integrations
- User-facing narrative should prefer `Mila` and `USMI suite`

---

## 8. Near-Term Implementation Priorities

### Phase 1: Strategy and Docs

- align USMI and ScaleScore docs to the workflow-first positioning
- update roadmap and technical spec to match the new contract

### Phase 2: Product Contract

- map current org-level signals into workflow-first readiness logic
- identify missing workflow metadata and evidence inputs
- define the Mila-native workflow submission contract for direct suite ingestion

### Phase 3: Integration and Packaging

- specify first Mila integration point for workflow scoring
- preserve compatibility mode while Mila-native workflow coverage expands
- package the standalone COO diagnostic/report offer

---

## 9. Explicit Non-Goals

- becoming a generic operations benchmarking platform
- owning runtime governance or compliance evidence operations
- removing the current org-level surface before workflow submission is ready
- expanding into unrelated benchmarking pillars that do not improve AI workflow readiness
