# ADR-0017: Open-Source Auth Provider Strategy

**Status**: Accepted  
**Date**: 2026-02-24  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore already supports:

- Internal JWT + refresh-token + API-key auth for standalone deployments (ADR-0011)
- Optional OpsOrchestra JWT trust mode for integrated deployments

The open question is how to add enterprise SSO without making Auth0 (or any vendor) mandatory for local development, open-source adopters, or self-hosted production users.

## Decision Drivers

- Keep the core product fully usable as open source without paid SaaS dependencies
- Preserve a clear enterprise path for SSO/OIDC integrations
- Avoid provider lock-in at the architecture level
- Keep CI and local development deterministic (no external auth dependency required)
- Maintain existing RBAC and tenant-isolation guarantees

## Considered Options

| Option | Summary | Pros | Cons |
|---|---|---|---|
| 1. Require Auth0 for all environments | Auth0 becomes default and mandatory | Faster hosted SSO setup, fewer auth variants | Breaks OSS portability, adds vendor dependency and cost, increases lock-in |
| 2. Internal auth only (no external IdP path) | Keep current JWT/API-key model only | Simple operations, no vendor coupling | Weak enterprise SSO story, harder B2B procurement |
| 3. Hybrid model (chosen) | Internal auth default + optional OIDC provider integration | OSS-first and self-host friendly, enterprise-ready, vendor-neutral | Additional implementation and test matrix complexity |

## Decision

Adopt the hybrid model.

1. Internal auth remains the default and first-class path for open-source, local, and self-hosted use.
2. External IdP integration is optional and standards-based (OIDC/JWKS), not Auth0-specific.
3. Auth0 is treated as a recommended provider profile for managed deployments, not a project requirement.
4. Core authorization remains provider-agnostic by normalizing claims into ScaleScore's canonical principal model before permission checks.

## Implementation Policy

### Baseline requirements

- The `/api/v1/auth/*` flow (signup/login/refresh/API keys) must remain supported.
- Development and CI must run successfully without an external IdP account.
- Provider-specific behavior must stay outside business logic and permission evaluation.

### External provider path

- External SSO support should be implemented via OIDC configuration and claim mapping.
- Any provider-specific setup guides (including Auth0) live in deployment docs, not as hardcoded runtime dependencies in core auth logic.
- If external IdP claims are missing required tenant/role information, requests fail closed.

### OpsOrchestra compatibility

- OpsOrchestra JWT trust mode remains a separate integration path and is unaffected by this decision.
- Claim normalization rules should remain explicit and configurable for all external token sources.

## Consequences

### Positive

- Open-source users can continue developing and deploying without Auth0.
- Enterprise customers still get a clear SSO path.
- Architecture remains resilient to provider changes.

### Negative

- More documentation and testing discipline is required across auth modes.
- Initial setup for optional OIDC support takes extra engineering effort.

### Neutral

- Existing internal JWT/API-key behavior does not change immediately.

## Related Decisions

- ADR-0011: Authentication and Authorization Strategy
- ADR-0016: User Management Strategy
- docs/ROADMAP.md (external dependency risk and mitigation)
