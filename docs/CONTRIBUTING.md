# Contributing to Proofhouse Readiness

Thank you for your interest in contributing to Proofhouse Readiness. This document provides guidelines and standards for contributing to the current `scalescore` technical repository.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Principles](#development-principles)
3. [Code Standards](#code-standards)
4. [Testing Requirements](#testing-requirements)
5. [Pull Request Process](#pull-request-process)
6. [Security Considerations](#security-considerations)

---

## Getting Started

### Repository naming note

Readiness is the public capability name for this layer in the current Proofhouse portfolio.

During this migration phase, the technical repo root, package name, CLI commands, env vars, auth claims, and API routes remain `scalescore`. `ScaleScore` should be treated as the current technical identifier and lineage reference. The future repo-root target is `proofhouse-readiness`, but that rename is a separate wave.

See [../NAMING.md](../NAMING.md) for the current product-vs-technical naming rules.

### Prerequisites

- Python 3.11 or 3.12
- Git
- (Optional) Docker for PostgreSQL

### Development Setup

```bash
# Clone the current technical repository
git clone https://github.com/im-sham/scalescore.git
# The checkout folder can remain "scalescore" until the repo-root rename wave.
cd scalescore

# Create a virtual environment owned by this checkout.
# Use Python 3.11 or 3.12; CI covers both supported minors.
# This example selects Python 3.12 to match its Python 3.12 constraint file.
# Every Git worktree must create its own .venv; never reuse another checkout's.
python3.12 -m venv .venv
source .venv/bin/activate

# This example is for Darwin arm64 with Python 3.12.
# On Linux x86_64, use the matching linux-x86_64 file instead.
# Python 3.11 users must select python3.11 and the matching Python 3.11 target file.
python -m pip install --constraint constraints/darwin-arm64-python3.12-dev.txt -e ".[dev]"

# Optional: install the separately constrained dashboard graph before launching it.
python -m pip install --constraint constraints/darwin-arm64-python3.12-frontend.txt -e ".[frontend]"

# Verify "Editable project location" is this checkout, then run tests.
python -m pip show scalescore
python scripts/run_tests.py -q --ignore=tests/integration/test_redis_rate_limit.py

# Run the demo
python -m scalescore.demo

# Start the API server
uvicorn scalescore.api.main:app --reload

# Launch the dashboard
streamlit run ui/streamlit_app.py
```

The standard test entrypoint is `python scripts/run_tests.py`. It imports `scalescore`
with the active interpreter and fails before importing or collecting pytest if the package
comes from another checkout. The diagnostic reports the interpreter, expected source,
imported path, and safe commands for rebuilding only the current checkout's `.venv`.

Runtime, development, and frontend dependencies are separate application graphs.
Select the exact constraint matching the active target and Python minor:
`-e .` with `runtime`, `-e ".[dev]"` with `dev`, or `-e ".[frontend]"` with
`frontend`. The frontend graph is optional and must not be used to audit the
core service dependency surface.

Use current technical identifiers in code, tooling, and tests until the repo-root rename wave is explicitly started.

### Project Structure

```
repo-root/
├── src/scalescore/
│   ├── api/              # FastAPI endpoints
│   ├── connectors/       # Data import connectors
│   ├── core/             # Core business logic
│   ├── models/           # Pydantic data models
│   └── scoring/          # Scoring engine and algorithms
├── tests/                # Test suite
├── ui/                   # Streamlit dashboard
├── data/                 # Demo dataset
└── docs/                 # Documentation
```

---

## Development Principles

These principles are non-negotiable. Please read and internalize them.

### 1. Build for Scale

> "Design for 100x. Implement for 10x. Validate at 1x."

Every change should consider:
- Will this work with 100x the current data volume?
- Is tenant isolation maintained?
- Are queries efficient (indexed, limited)?
- Would this require refactoring at scale?

**Examples:**
- ✅ Use pagination for list endpoints
- ✅ Include `org_id` in all database queries
- ❌ Load all entities into memory
- ❌ Hardcode limits that don't scale

### 2. Graceful Architecture

> "Complexity is the enemy. Fight it relentlessly."

Every change should:
- Follow established patterns (check ARCHITECTURE.md)
- Have clear, single responsibility
- Be explicit rather than clever
- Include appropriate abstraction (but not too much)

**Examples:**
- ✅ New service follows existing service patterns
- ✅ New models go in appropriate module
- ❌ Business logic in API routes
- ❌ Database queries in domain models

### 3. Security-First

> "Assume breach. Protect data. Earn trust."

Every change should consider:
- Is sensitive data classified and handled appropriately?
- Are inputs validated?
- Is tenant isolation maintained?
- Is the change auditable?

**Examples:**
- ✅ Validate all user inputs with Pydantic
- ✅ Classify new fields (public/internal/confidential)
- ❌ Log sensitive data without masking
- ❌ Skip authorization checks

---

## Code Standards

### Python Style

We use **Ruff** for linting and formatting:

```bash
# Run linter
ruff check src/ tests/

# Fix auto-fixable issues
ruff check --fix src/ tests/

# Format code
ruff format src/ tests/
```

### Type Hints

All code must have type hints. We use **mypy** for type checking:

```bash
mypy src/
```

**Standards:**
- All function parameters and returns must be typed
- Use `| None` instead of `Optional[X]`
- Use `list[X]` instead of `List[X]` (Python 3.9+ style)
- Avoid `Any` unless absolutely necessary

```python
# Good
def calculate_score(constraints: list[CapacityConstraint], now: datetime | None = None) -> float:
    ...

# Bad
def calculate_score(constraints, now=None):
    ...
```

### Naming Conventions

| Entity | Convention | Example |
|--------|------------|---------|
| Classes | PascalCase | `ScoringEngine` |
| Functions | snake_case | `calculate_area_score` |
| Variables | snake_case | `constraint_penalty` |
| Constants | UPPER_SNAKE_CASE | `DEFAULT_TIMEOUT` |
| Private | Leading underscore | `_internal_method` |
| Modules | snake_case | `bottleneck_detector.py` |

### Imports

Organize imports in this order:
1. Standard library
2. Third-party packages
3. Local imports

```python
# Standard library
from datetime import datetime
from typing import Any

# Third-party
from fastapi import FastAPI, Depends
from pydantic import BaseModel

# Local
from scalescore.models.core import Organization
from scalescore.scoring.engine import ScoringEngine
```

### Docstrings

Use Google-style docstrings for all public functions and classes:

```python
def calculate_area_score(
    org_id: str,
    area: FunctionalArea,
    constraints: list[CapacityConstraint],
) -> ReadinessScore:
    """Calculate readiness score for a functional area.
    
    Args:
        org_id: Organization identifier.
        area: Functional area to score.
        constraints: List of constraints affecting this area.
        
    Returns:
        ReadinessScore with calculated score and breakdown.
        
    Raises:
        ValueError: If org_id is empty.
    """
    ...
```

---

## Testing Requirements

### Coverage Requirements

| Component | Minimum Coverage |
|-----------|------------------|
| Core scoring | 80% |
| API routes | 70% |
| Connectors | 70% |
| Models | 60% (mostly Pydantic validation) |

### Running Tests

```bash
# Run all tests
python scripts/run_tests.py

# Run with coverage
python scripts/run_tests.py --cov=src/scalescore --cov-report=html

# Run a specific test file
python scripts/run_tests.py tests/unit/scoring/test_scoring_engine.py

# Run tests matching a pattern
python scripts/run_tests.py -k "test_score"
```

### Test Structure

```python
# tests/test_scoring_engine.py

def test_score_penalizes_constraints() -> None:
    """Score should decrease with constraints."""
    # Arrange
    engine = ScoringEngine()
    constraint = CapacityConstraint(...)
    
    # Act
    result = engine.calculate_area_score(
        org_id="org_1",
        area=FunctionalArea.ENGINEERING,
        constraints=[constraint],
        risks=[],
        growth_signals=[],
    )
    
    # Assert
    assert result.score < 100
    assert result.constraint_count == 1
```

### Test Naming

Use descriptive test names that explain behavior:

```python
# Good
def test_growth_signal_increases_penalty() -> None: ...
def test_critical_risk_has_higher_multiplier() -> None: ...
def test_empty_constraints_returns_full_score() -> None: ...

# Bad
def test_score() -> None: ...
def test_calculate() -> None: ...
```

---

## Pull Request Process

### Before Submitting

- [ ] Code passes `ruff check` and `ruff format`
- [ ] Code passes `mypy` type checking
- [ ] All tests pass
- [ ] New code has tests
- [ ] Documentation updated if needed
- [ ] ADR created for architectural decisions
- [ ] Security checklist reviewed (see below)

### PR Template

```markdown
## Summary
Brief description of changes.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Refactoring
- [ ] Documentation
- [ ] Other

## Testing
How was this tested?

## Security Checklist
- [ ] No secrets in code
- [ ] Inputs validated
- [ ] Tenant isolation maintained
- [ ] Sensitive data handled appropriately

## Related Issues
Closes #123
```

### Review Criteria

PRs are reviewed for:
1. **Correctness**: Does it work as intended?
2. **Architecture**: Does it follow patterns in ARCHITECTURE.md?
3. **Security**: Does it follow SECURITY.md guidelines?
4. **Performance**: Will it scale?
5. **Testing**: Is it adequately tested?
6. **Documentation**: Is it documented?

---

## Security Considerations

### Pre-Commit Checks

Before every commit, verify:

- [ ] No secrets (API keys, passwords) in code
- [ ] No sensitive data in logs
- [ ] Inputs validated with Pydantic
- [ ] Tenant isolation maintained (queries include `org_id`)
- [ ] Error messages don't leak internal details

### Sensitive Data Handling

New fields must be classified:

```python
from pydantic import Field

class Organization(BaseModel):
    # Internal: tenant-isolated, logged normally
    name: str = Field(..., json_schema_extra={"classification": "internal"})
    
    # Confidential: masked in logs, encrypted at rest
    revenue_current: float = Field(
        ..., 
        json_schema_extra={"classification": "confidential"}
    )
```

### Dependency Policy

New dependencies require justification:
1. Is it actively maintained?
2. Does it have known vulnerabilities?
3. Is it necessary (or can stdlib work)?
4. Is the license compatible (MIT, Apache 2.0, BSD)?

Keep reusable dependency declarations as lower bounds in `pyproject.toml`.
The files under `constraints/` capture target-specific Readiness development
and CI dependency graphs for Darwin arm64 and Linux x86_64 on Python 3.11 and
3.12. They are not cross-platform lock files and do not describe a production
image.

After changing dependency metadata or accepting dependency updates, generate
and check each supported graph inside a matching Darwin arm64 or Linux x86_64
Python environment with the corresponding supported minor. Each invocation
handles that target and minor's three runtime, development, and frontend graphs:

```bash
# Run these on Darwin arm64.
python3.11 scripts/compile_dependency_constraints.py
python3.12 scripts/compile_dependency_constraints.py

# Run these separately in a Linux x86_64 environment. An emulated x86_64 Linux
# container is acceptable when the guest reports Linux/x86_64 and Python matches
# the selected supported minor.
python3.11 scripts/compile_dependency_constraints.py
python3.12 scripts/compile_dependency_constraints.py
```

Generation upgrades accepted pins. Check mode seeds temporary copies of all
three tracked files for the active target and minor, then byte-compares
regenerated output without creating checkout paths or mutating tracked files:

```bash
python3.11 scripts/compile_dependency_constraints.py --check
python3.12 scripts/compile_dependency_constraints.py --check
```

The compiler rejects unsupported platform/architecture combinations and Python
minors. Do not generate one target's files from another target environment or
hand-edit a partial transitive graph.

Dependabot dependency PRs must include all 12 regenerated target/minor/kind
constraints, pass target-specific drift checks and `pip check`, and audit all
12 exact files. Do not add an advisory ignore or exception to make CI pass.

---

## Getting Help

- **Questions about code**: Open an issue or discussion
- **Security concerns**: Email security@scalescore.io directly
- **Architecture decisions**: Check docs/adr/ or create new ADR

---

## Recognition

Contributors who submit accepted PRs will be added to CONTRIBUTORS.md.

Thank you for contributing to Proofhouse Readiness.
