# ADR-0018: Production Container Artifact

**Status**: Accepted
**Date**: 2026-07-20
**Author**: Engineering
**Reviewers**: Product Owner

## Context

Readiness has exact cross-platform runtime, development, and frontend constraint graphs, but those graphs intentionally did not choose a production target or define a deployable artifact. WP-RI-05 requires a bounded artifact contract without making deployment, orchestration, provider, traffic, or customer decisions.

## Decision Drivers

- Produce one verifiable artifact from the accepted core runtime graph.
- Keep the API and optional worker on identical application code and dependencies.
- Preserve the supported Python 3.11/3.12 library and development contracts.
- Exclude the MVP Streamlit dependency graph from production artifact claims.
- Fail closed on High or Critical image vulnerabilities, including unfixed findings.

## Decision

The canonical Readiness artifact platform is Linux x86_64 with Python 3.12. Readiness builds one shared core image. The same immutable image launches either the FastAPI API command or the `scalescore-worker` command; a separate worker process is required only when the selected async configuration requires it.

The Streamlit application and the `frontend` optional dependency graph are excluded from this production artifact. This exclusion does not decide or cancel future UX work.

The production lock is derived from `constraints/linux-x86_64-python3.12-runtime.txt`, adds distribution hashes, and is installed with hash verification. CI builds and smoke-checks the image, records the final installed Python inventory, generates a CycloneDX SBOM, requires exact bidirectional package/version parity, and blocks on Grype High or Critical findings without ignores, waivers, VEX, only-fixed filtering, severity downgrade, or vulnerability exceptions. CI records immutable image and archive digests and retains the bounded rollback artifact for 30 days.

## Consequences

### Positive

- API and worker cannot drift into different production dependency sets.
- The final installed runtime and SBOM are directly comparable.
- Artifact identity and rollback material are retained for a bounded period.
- Frontend-only packages do not expand the core production attack surface.

### Negative

- Linux x86_64 is the only production artifact platform in this decision.
- High or Critical upstream findings block the artifact even when no fix exists.
- A separate frontend production artifact requires a future explicit decision.

### Neutral

- Python 3.11 remains supported for the existing library, development, and test contracts; it is not the production image minor.
- This ADR does not select or authorize orchestration, a cloud/provider, deployment, credentials, traffic, production operation, external users, customer or partner activity, live data, external claims, protected-branch changes, G2 closure, or overall WP-RI-05 closure.

## Related Decisions

- ADR-0012: Background Job Processing
- ADR-0013: Testing Strategy
- ADR-0017: Open-Source Auth Provider Strategy
