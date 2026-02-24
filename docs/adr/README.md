# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records for ScaleScore.

## What is an ADR?

An Architecture Decision Record captures a significant architectural decision along with its context and consequences. ADRs help us:

- **Preserve context**: Understand *why* decisions were made
- **Onboard new team members**: Learn the history of the codebase
- **Evaluate changes**: Assess whether original constraints still apply
- **Avoid repeated discussions**: Reference past decisions

## ADR Index

### Foundation (ADR-0001 to ADR-0006)

Core architectural decisions for the ScaleScore platform.

| ID | Title | Status | Date |
|----|-------|--------|------|
| [ADR-0001](./0001-use-pydantic-v2-for-models.md) | Use Pydantic v2 for Data Models | Accepted | Jan 2026 |
| [ADR-0002](./0002-fastapi-for-api-layer.md) | Use FastAPI for API Layer | Accepted | Jan 2026 |
| [ADR-0003](./0003-constraint-based-scoring.md) | Constraint-Based Scoring Algorithm | Accepted | Jan 2026 |
| [ADR-0004](./0004-repository-pattern-for-data-access.md) | Repository Pattern for Data Access | Accepted | Jan 2026 |
| [ADR-0005](./0005-multi-tenancy-strategy.md) | Shared Database Multi-Tenancy | Accepted | Jan 2026 |
| [ADR-0006](./0006-postgresql-as-primary-database.md) | PostgreSQL as Primary Database | Accepted | Jan 2026 |

### Cross-Cutting Concerns (ADR-0007 to ADR-0012)

Decisions covering error handling, observability, security, and infrastructure.

| ID | Title | Status | Date |
|----|-------|--------|------|
| [ADR-0007](./0007-error-handling-strategy.md) | Error Handling Strategy | Accepted | Jan 2026 |
| [ADR-0008](./0008-api-versioning-strategy.md) | API Versioning Strategy | Accepted | Jan 2026 |
| [ADR-0009](./0009-configuration-management.md) | Configuration Management | Accepted | Jan 2026 |
| [ADR-0010](./0010-structured-logging-observability.md) | Structured Logging and Observability | Accepted | Jan 2026 |
| [ADR-0011](./0011-authentication-authorization-strategy.md) | Authentication and Authorization Strategy | Accepted | Jan 2026 |
| [ADR-0012](./0012-background-job-processing.md) | Background Job Processing | Accepted | Jan 2026 |

### Domain & Quality (ADR-0013 to ADR-0017)

Decisions covering testing, domain-specific engines, and data integrity.

| ID | Title | Status | Date |
|----|-------|--------|------|
| [ADR-0013](./0013-testing-strategy.md) | Testing Strategy | Accepted | Jan 2026 |
| [ADR-0014](./0014-dependency-graph-engine.md) | Dependency Graph Engine (NetworkX) | Accepted | Jan 2026 |
| [ADR-0015](./0015-report-immutability-versioning.md) | Report Immutability and Versioning | Accepted | Jan 2026 |
| [ADR-0016](./0016-user-management-strategy.md) | User Management Strategy | Proposed | Feb 2026 |
| [ADR-0017](./0017-open-source-auth-provider-strategy.md) | Open-Source Auth Provider Strategy | Accepted | Feb 2026 |

## ADR Lifecycle

| Status | Description |
|--------|-------------|
| **Proposed** | Under discussion, not yet accepted |
| **Accepted** | Decision made and being implemented |
| **Deprecated** | No longer applies but kept for historical reference |
| **Superseded** | Replaced by a newer ADR (link to replacement) |

## When to Write an ADR

Write an ADR when:
- Choosing between multiple viable technical approaches
- Making a decision that will be hard to reverse
- Introducing a new technology, pattern, or dependency
- Changing an existing architectural pattern
- Making a security-related decision

## ADR Template

```markdown
# ADR-NNNN: Title

**Status**: Proposed | Accepted | Deprecated | Superseded by ADR-XXXX
**Date**: YYYY-MM-DD
**Author**: Name
**Reviewers**: Names

## Context

What is the issue that we're seeing that motivates this decision?

## Decision Drivers

- Driver 1
- Driver 2
- Driver 3

## Considered Options

### Option 1: [Name]
Description of the option.

**Pros:**
- Pro 1
- Pro 2

**Cons:**
- Con 1
- Con 2

### Option 2: [Name]
...

## Decision

What is the decision that was made?

## Consequences

### Positive
- Consequence 1
- Consequence 2

### Negative
- Consequence 1
- Consequence 2

### Neutral
- Consequence 1

## Related Decisions

- ADR-XXXX: Related decision
- ADR-YYYY: Another related decision

## Notes

Any additional context, links, or references.
```

## Creating a New ADR

1. Copy the template above
2. Name the file `NNNN-short-title.md` (use next available number)
3. Fill in all sections
4. Submit as PR for review
5. Update this index once accepted
