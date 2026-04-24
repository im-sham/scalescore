# Proofhouse Readiness Documentation

> **Documentation Philosophy**: Every architectural decision, security consideration, and implementation choice should be documented with enough context that future developers understand not just *what* was decided, but *why*.

---

## Repository Scope Note

This is the active technical documentation set for the current `scalescore` repo.

Public Proofhouse naming describes this capability as `Readiness`, but the repo root, package/module names, CLI commands, env vars, auth settings, and API routes remain `scalescore` until a later migration wave explicitly changes them.

The canonical naming note is [../NAMING.md](../NAMING.md).

---

## Documentation Structure

```
docs/
├── README.md                    # This file - documentation index
├── TECHNICAL_SPEC.md           # Product specification and requirements
├── ARCHITECTURE.md             # System architecture and design principles
├── API.md                      # API reference and auth/integration workflows
├── ROADMAP.md                  # Implementation roadmap with milestones
├── SECURITY.md                 # Security architecture and compliance
├── SECURITY_BASELINE.md        # Executed checks and current security posture
├── SECURITY_OWASP_API_TOP10_AUDIT.md # OWASP API Top 10 control audit evidence
├── STAGING_VALIDATION.md       # Release-gate validation runbook for staging
├── CONTRIBUTING.md             # Development standards and practices
├── OPERATOR_QUICKSTART.md      # Non-technical onboarding flow
├── architecture/
│   └── ADR_GAP_ANALYSIS.md     # Historical architect assessment snapshot
├── adr/
│   ├── README.md               # ADR index and template
│   ├── 0001-use-pydantic-v2-for-models.md
│   ├── ...
│   └── 0017-open-source-auth-provider-strategy.md
```

Top-level [../NAMING.md](../NAMING.md) holds the product-vs-technical naming rules for this repo.

Top-level [../CONTRACTS.md](../CONTRACTS.md) maps Readiness to the Proofhouse shared-contract registry.

---

## Core Documents

| Document | Purpose | Audience |
|----------|---------|----------|
| [TECHNICAL_SPEC.md](./TECHNICAL_SPEC.md) | Product requirements, features, and specifications | Product, Engineering |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System design, principles, and patterns | Engineering, Architecture |
| [API.md](./API.md) | Endpoint reference, auth methods, and integration examples | Engineering, Integrations |
| [ROADMAP.md](./ROADMAP.md) | Implementation phases, milestones, and priorities | All stakeholders |
| [SECURITY.md](./SECURITY.md) | Security architecture, compliance, data handling | Engineering, Security, Compliance |
| [SECURITY_BASELINE.md](./SECURITY_BASELINE.md) | Baseline scan/test results and current risks | Engineering, Security |
| [SECURITY_OWASP_API_TOP10_AUDIT.md](./SECURITY_OWASP_API_TOP10_AUDIT.md) | OWASP API Top 10 mapping and pass/fail evidence | Engineering, Security |
| [STAGING_VALIDATION.md](./STAGING_VALIDATION.md) | Staging smoke checks and release exit criteria | Engineering, Operations |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Development standards, code style, PR process | Engineering |
| [OPERATOR_QUICKSTART.md](./OPERATOR_QUICKSTART.md) | 15-minute operator flow with CSV-based assessment | Operations, Customer Teams |
| [../GOVERNANCE.md](../GOVERNANCE.md) | Governance model, maintainer responsibilities, decision process | Maintainers, Contributors |
| [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Community standards and moderation expectations | All contributors |

---

## Architecture Decision Records (ADRs)

We use ADRs to capture significant architectural decisions. This ensures:
- **Context preservation**: Why decisions were made
- **Trade-off documentation**: What alternatives were considered
- **Change tracking**: How our architecture evolves

See [adr/README.md](./adr/README.md) for the ADR index and template.

---

## Guiding Principles

These principles inform all documentation and technical decisions:

### 1. Build for Scale
> "Make architecture decisions that don't require circling back on tech debt."

- Choose patterns that support 100x growth without redesign
- Prefer horizontal scalability over vertical
- Design for multi-tenancy from day one
- Document scaling implications of every major decision

### 2. Graceful Architecture
> "Clean, efficient, and maintainable. Best practices are the baseline, not the goal."

- Separation of concerns is non-negotiable
- Interfaces before implementations
- Explicit over implicit behavior
- Code should be self-documenting; docs should explain *why*

### 3. Security-First
> "SOC2-level quality. Businesses trust us with sensitive data."

- Assume breach mentality in design
- Principle of least privilege everywhere
- Audit logging for all sensitive operations
- Data classification and handling policies enforced in code

---

## Document Maintenance

| Trigger | Action |
|---------|--------|
| New feature or component | Update TECHNICAL_SPEC.md, consider ADR |
| Architectural change | Create ADR, update ARCHITECTURE.md |
| Security-relevant change | Update SECURITY.md, document in ADR |
| API change | Update TECHNICAL_SPEC.md and ROADMAP.md to reflect the live route surface |
| Dependency addition | Document rationale in ADR or CONTRIBUTING.md |

---

## Getting Started

1. **New to the project?** Start with [README.md](../README.md) then [TECHNICAL_SPEC.md](./TECHNICAL_SPEC.md)
2. **Contributing code?** Read [CONTRIBUTING.md](./CONTRIBUTING.md) and [ARCHITECTURE.md](./ARCHITECTURE.md)
3. **Security review?** See [SECURITY.md](./SECURITY.md)
4. **Understanding a decision?** Check [adr/](./adr/) for context
