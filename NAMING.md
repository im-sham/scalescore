# Proofhouse Readiness Naming

This repository is in a naming transition.

## Active Product Language

Use **Proofhouse Readiness** or **Readiness** in product docs, roadmap docs, customer-facing copy, and suite-level architecture notes.

Readiness owns:

- workflow readiness scoring
- trust-gap diagnosis
- remediation prioritization
- organization rollups derived from workflow assessments
- Operational Learning suitability scoring as a sibling lens

## Current Technical Identifiers

Keep `scalescore` for current code, package imports, CLI commands, env vars, auth claims, API routes, worker names, and repository references until a dedicated rename wave changes them.

`ScaleScore` remains acceptable when referring to:

- the current technical service
- historical docs and ADRs
- concrete classes such as `ScaleScoreReport`
- compatibility-mode API behavior

## Suite Boundary

Readiness does not own canonical workflow truth, rights approvals, redaction review, export eligibility, promotion approvals, asset derivation, or incident memory.

| Capability | Current responsibility |
|------------|------------------------|
| Workflow Context | Canonical workflow truth, system of work, evidence linkage, operational context |
| Readiness | Suitability scoring, readiness scoring, trust-gap diagnosis, remediation prioritization |
| Governance | Rights, policy, redaction review, use approvals, export control, manifests, audit-grade use control |
| Forge | Incident memory, failure-pattern learning, scoring-model feedback |

## Operational Learning Boundary

Operational Learning suitability is a Readiness scoring lens. It can say whether a workflow appears suitable for internal eval use or internal training candidacy, including why it is blocked.

It cannot approve use. Governance remains the approval plane for rights, redaction, promotion, export, and residual-risk decisions.
