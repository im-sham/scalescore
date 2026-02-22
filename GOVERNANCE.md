# ScaleScore Governance

> **Last Updated:** February 22, 2026  
> **Status:** Active  
> **Scope:** Open source ScaleScore repository

---

## Mission

ScaleScore exists to help organizations identify operational bottlenecks before they become failures.  
Governance keeps the project reliable, transparent, and contributor-friendly as adoption grows.

---

## Project Scope

This repository covers:
- ScaleScore core models, scoring engine, API, CLI, and UI.
- Documentation, examples, and integration interfaces.
- Public contribution workflows and release practices.

Out of scope for this governance document:
- Commercial services or managed offerings.
- Internal OpsOrchestra/Mila product governance.

## Public vs Internal Documentation Boundary

- Public repo docs should contain product behavior, contributor workflows, architecture, and user guidance.
- Internal strategy, GTM sequencing, partner plans, and sensitive operating notes should stay outside the public repo.
- If local internal notes are needed in this workspace, keep them under `docs/_internal/` or `*.internal.md` paths (gitignored).

---

## Roles

## Maintainers

Maintainers are responsible for project direction and merge authority.

Responsibilities:
- Review and merge pull requests.
- Keep roadmap and architectural direction coherent.
- Enforce security, quality, and release standards.
- Triage issues and label contribution opportunities.

## Contributors

Contributors are anyone submitting issues, docs updates, code, tests, or proposals.

Responsibilities:
- Follow contribution and testing guidelines.
- Keep changes focused and documented.
- Participate constructively in review discussions.

## Release Manager (Rotating)

One maintainer per release cycle acts as release manager.

Responsibilities:
- Build release candidate and validate CI/test status.
- Confirm release notes and version bump.
- Publish and announce release artifacts.

---

## Decision-Making Model

## Default path: Maintainer Consensus

- Small and medium changes are decided via PR discussion and maintainer approval.
- A change is accepted when at least one maintainer approves and no unresolved blocking concerns remain.

## Architectural changes: ADR-driven

- Significant architecture or interface changes require an ADR update under `docs/adr/`.
- ADRs must capture context, alternatives, decision, and consequences.

## Escalation path

- If maintainers disagree, the designated release manager proposes a decision summary.
- If disagreement remains, repository owner makes the final call for that cycle.

---

## Contribution and Review Policy

- Use the process in `docs/CONTRIBUTING.md`.
- All non-trivial changes require tests or documented rationale for why tests are not feasible.
- Security-relevant changes should reference `docs/SECURITY.md`.
- PRs should stay narrowly scoped; unrelated changes are likely to be deferred.

---

## Release Policy

- Versioning follows semantic versioning (`MAJOR.MINOR.PATCH`).
- Major releases may include breaking API or model changes.
- Minor releases add features in backward-compatible ways.
- Patch releases are for fixes and security updates.

Release cadence target:
- Minor releases: bi-weekly.
- Patch releases: as needed.
- Major releases: quarterly or when justified by scope.

---

## Security and Responsible Disclosure

- Do not open public issues for unpatched high-risk vulnerabilities.
- Follow the reporting process in `docs/SECURITY.md`.
- Maintainers prioritize security triage and patch response ahead of roadmap items when warranted.

---

## Communication Channels

- **Issues:** bug reports, feature requests, task discussions.
- **Pull Requests:** implementation and review.
- **Roadmap docs:** medium-term prioritization and sequencing.

---

## Governance Updates

Governance is a living document.  
Changes should be proposed via pull request and reviewed by maintainers like any other project change.
