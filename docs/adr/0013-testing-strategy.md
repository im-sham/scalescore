# ADR-0013: Testing Strategy

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore needs a comprehensive testing strategy to ensure:

- **Quality**: Code works correctly as intended
- **Reliability**: Changes don't break existing functionality
- **Confidence**: Safe to deploy to production
- **Documentation**: Tests serve as executable specifications
- **Performance**: System meets performance requirements

Currently, the project has:
- pytest as test runner
- Basic fixtures in conftest.py
- Unit tests for scoring engine (~60% estimated coverage)
- No integration tests
- No performance tests
- No end-to-end tests

As the system grows, we need a formal testing strategy that scales with complexity.

## Decision Drivers

- **Fast Feedback**: Tests should run quickly in development
- **Comprehensive Coverage**: Critical paths must be tested
- **Maintainability**: Tests should be easy to write and maintain
- **CI/CD Integration**: Tests must run in automated pipelines
- **Cost-Effective**: Testing effort balanced with value
- **Multi-tenancy**: Tests must verify tenant isolation

## Considered Options

### Option 1: Test Pyramid (Unit → Integration → E2E)

Traditional testing pyramid with emphasis on unit tests.

**Pros:**
- Fast test suite (mostly unit tests)
- Clear separation of concerns
- Industry standard approach
- Catches issues early
- Easy to maintain

**Cons:**
- Requires discipline to maintain pyramid shape
- Integration points may be under-tested
- E2E tests are slow and flaky

### Option 2: Testing Trophy (Integration-Heavy)

More integration tests, fewer unit tests (Kent C. Dodds style).

**Pros:**
- Tests closer to real usage
- Catches integration bugs
- Less test code to maintain

**Cons:**
- Slower test suite
- Harder to isolate failures
- More complex setup
- Larger blast radius for failures

### Option 3: Behavior-Driven Development (BDD)

Gherkin-style specifications with Cucumber/Behave.

**Pros:**
- Business-readable specifications
- Living documentation
- Stakeholder involvement

**Cons:**
- Additional abstraction layer
- Learning curve
- Verbose for simple tests
- Overkill for technical APIs

## Decision

**Use Option 1: Test Pyramid with defined coverage targets.**

We will implement:
1. **Unit Tests (70%)**: Fast, isolated component tests
2. **Integration Tests (20%)**: Component interaction tests
3. **E2E/API Tests (10%)**: Full system validation
4. **Performance Tests**: Baseline and regression testing
5. **Coverage Targets**: 80% overall, 90% for core scoring

Rationale:
- Test pyramid provides fast feedback with comprehensive coverage
- Unit tests are maintainable and fast
- Integration tests catch interaction bugs
- E2E tests verify production readiness
- Balances thoroughness with development velocity

## Consequences

### Positive
- Fast test suite enables rapid iteration
- High coverage reduces production bugs
- Clear testing responsibilities
- CI/CD integration straightforward
- Tests document expected behavior

### Negative
- Initial investment to establish patterns
- Ongoing discipline to maintain pyramid
- Mock management for unit tests

### Neutral
- Requires testing infrastructure (fixtures, factories)
- Coverage thresholds may need tuning

## Implementation Notes

### Test Structure

```
tests/
├── conftest.py                 # Shared fixtures
├── factories/                  # Test data factories
│   ├── __init__.py
│   ├── organization.py
│   ├── assessment.py
│   └── user.py
├── unit/                       # Unit tests (fast, isolated)
│   ├── __init__.py
│   ├── scoring/
│   │   ├── test_engine.py
│   │   ├── test_bottleneck.py
│   │   └── test_recommendations.py
│   ├── models/
│   │   ├── test_core.py
│   │   └── test_scaling.py
│   └── connectors/
│       └── test_csv_connector.py
├── integration/                # Integration tests
│   ├── __init__.py
│   ├── test_assessment_flow.py
│   ├── test_repository.py
│   └── test_auth.py
├── e2e/                        # End-to-end API tests
│   ├── __init__.py
│   ├── test_api_health.py
│   ├── test_api_assessments.py
│   └── test_api_auth.py
└── performance/                # Performance tests
    ├── __init__.py
    ├── test_scoring_perf.py
    └── locustfile.py           # Load testing
```

### Test Configuration

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--tb=short",
    "--strict-markers",
    "--strict-config",
]
markers = [
    "unit: Unit tests (fast, isolated)",
    "integration: Integration tests (require dependencies)",
    "e2e: End-to-end tests (full system)",
    "performance: Performance tests (slow)",
    "slow: Tests that take >1s",
]
filterwarnings = [
    "error",
    "ignore::DeprecationWarning",
]

[tool.coverage.run]
source = ["src/scalescore"]
branch = true
omit = [
    "*/tests/*",
    "*/__init__.py",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
]
fail_under = 80
show_missing = true
```

### Shared Fixtures

```python
# tests/conftest.py
import pytest
from typing import Generator
from unittest.mock import MagicMock

from scalescore.config import Settings
from scalescore.models.core import Organization, Team, System
from scalescore.models.scaling import GrowthSignal


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Test configuration."""
    return Settings(
        environment="testing",
        database__host="localhost",
        database__name="scalescore_test",
    )


@pytest.fixture
def sample_organization() -> Organization:
    """Create a sample organization for testing."""
    return Organization(
        id="org-test-001",
        name="Test Organization",
        headcount_current=100,
        headcount_planned=150,
        revenue_current=10_000_000,
        revenue_planned=15_000_000,
    )


@pytest.fixture
def sample_growth_signals() -> list[GrowthSignal]:
    """Create sample growth signals."""
    return [
        GrowthSignal(
            signal_id="growth-001",
            entity_id="org-test-001",
            signal_type="headcount",
            current_value=100,
            projected_value=150,
            timeframe_months=12,
            confidence=0.8,
        ),
    ]


@pytest.fixture
def mock_repository():
    """Create a mock repository."""
    repo = MagicMock()
    repo.get_by_id.return_value = None
    repo.save.return_value = None
    return repo


# Database fixtures for integration tests
@pytest.fixture(scope="function")
def db_session(test_settings):
    """Create a test database session with rollback."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(test_settings.database.url_with_password)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.rollback()
    session.close()


# API client for e2e tests
@pytest.fixture
def api_client(test_settings):
    """Create a test API client."""
    from fastapi.testclient import TestClient
    from scalescore.api.main import create_app
    
    app = create_app(settings=test_settings)
    return TestClient(app)


@pytest.fixture
def authenticated_client(api_client, test_user):
    """Create an authenticated API client."""
    from scalescore.core.auth.jwt import JWTService
    
    jwt_service = JWTService()
    token = jwt_service.create_access_token(
        user_id=test_user.id,
    org_id=test_user.org_id,
        email=test_user.email,
        roles=test_user.roles,
    )
    
    api_client.headers["Authorization"] = f"Bearer {token}"
    return api_client
```

### Test Factories

```python
# tests/factories/organization.py
from typing import Any
from uuid import uuid4

from scalescore.models.core import Organization, Team, System


class OrganizationFactory:
    """Factory for creating test organizations."""
    
    @staticmethod
    def create(
        id: str | None = None,
        name: str = "Test Organization",
        headcount_current: int = 100,
        headcount_planned: int = 150,
        **kwargs: Any,
    ) -> Organization:
        return Organization(
            id=id or f"org-{uuid4().hex[:8]}",
            name=name,
            headcount_current=headcount_current,
            headcount_planned=headcount_planned,
            **kwargs,
        )
    
    @staticmethod
    def create_with_teams(
        num_teams: int = 3,
        **org_kwargs: Any,
    ) -> tuple[Organization, list[Team]]:
        """Create organization with teams."""
        org = OrganizationFactory.create(**org_kwargs)
        teams = [
            Team(
                id=f"team-{i}",
                name=f"Team {i}",
                organization_id=org.id,
                headcount_current=10 + i * 5,
            )
            for i in range(num_teams)
        ]
        return org, teams


class AssessmentFactory:
    """Factory for creating test assessment data."""
    
    @staticmethod
    def create_full_dataset() -> dict[str, Any]:
        """Create a complete dataset for assessment testing."""
        org, teams = OrganizationFactory.create_with_teams()
        
        return {
            "organizations": [org],
            "teams": teams,
            "systems": [],
            "vendors": [],
            "facilities": [],
        }
```

### Unit Test Example

```python
# tests/unit/scoring/test_engine.py
import pytest
from scalescore.scoring.engine import ScoringEngine
from scalescore.models.scaling import CapacityConstraint, ReadinessScore


class TestScoringEngine:
    """Unit tests for ScoringEngine."""
    
    @pytest.fixture
    def engine(self) -> ScoringEngine:
        return ScoringEngine()
    
    @pytest.mark.unit
    def test_base_score_is_100(self, engine: ScoringEngine) -> None:
        """Verify base score without constraints is 100."""
        result = engine.calculate_area_score(
            area="operations",
            constraints=[],
            growth_signals=[],
        )
        
        assert result.score == 100.0
        assert result.area == "operations"
    
    @pytest.mark.unit
    def test_constraint_reduces_score(self, engine: ScoringEngine) -> None:
        """Verify constraints reduce the score."""
        constraint = CapacityConstraint(
            entity_id="test-001",
            constraint_type="headcount",
            severity="high",
            current_utilization=0.95,
            max_capacity=100,
        )
        
        result = engine.calculate_area_score(
            area="operations",
            constraints=[constraint],
            growth_signals=[],
        )
        
        assert result.score < 100.0
        assert result.constraint_count == 1
    
    @pytest.mark.unit
    def test_critical_severity_higher_penalty(self, engine: ScoringEngine) -> None:
        """Verify critical severity has higher penalty than high."""
        critical = CapacityConstraint(
            entity_id="test-001",
            constraint_type="capacity",
            severity="critical",
            current_utilization=0.95,
            max_capacity=100,
        )
        
        high = CapacityConstraint(
            entity_id="test-002",
            constraint_type="capacity",
            severity="high",
            current_utilization=0.95,
            max_capacity=100,
        )
        
        critical_result = engine.calculate_area_score(
            area="operations",
            constraints=[critical],
            growth_signals=[],
        )
        
        high_result = engine.calculate_area_score(
            area="operations",
            constraints=[high],
            growth_signals=[],
        )
        
        assert critical_result.score < high_result.score
    
    @pytest.mark.unit
    def test_score_never_negative(self, engine: ScoringEngine) -> None:
        """Verify score is clamped to minimum 0."""
        many_constraints = [
            CapacityConstraint(
                entity_id=f"test-{i}",
                constraint_type="capacity",
                severity="critical",
                current_utilization=0.99,
                max_capacity=100,
            )
            for i in range(50)
        ]
        
        result = engine.calculate_area_score(
            area="operations",
            constraints=many_constraints,
            growth_signals=[],
        )
        
        assert result.score >= 0.0
```

### Integration Test Example

```python
# tests/integration/test_assessment_flow.py
import pytest
from pathlib import Path

from scalescore.assessment import run_assessment_from_csv
from scalescore.models.scaling import ScaleScoreReport


class TestAssessmentFlow:
    """Integration tests for full assessment flow."""
    
    @pytest.fixture
    def sample_data_dir(self, tmp_path: Path) -> Path:
        """Create sample CSV files for testing."""
        # Create organizations.csv
        (tmp_path / "organizations.csv").write_text(
            "id,name,headcount_current,headcount_planned,revenue_current,revenue_planned\n"
            "org-001,Test Org,100,150,10000000,15000000\n"
        )
        
        # Create teams.csv
        (tmp_path / "teams.csv").write_text(
            "id,name,organization_id,headcount_current\n"
            "team-001,Engineering,org-001,50\n"
            "team-002,Sales,org-001,30\n"
        )
        
        return tmp_path
    
    @pytest.mark.integration
    def test_csv_to_report(self, sample_data_dir: Path) -> None:
        """Test complete flow from CSV to report."""
        report = run_assessment_from_csv(sample_data_dir)
        
        assert isinstance(report, ScaleScoreReport)
        assert report.organization_id == "org-001"
        assert 0 <= report.overall_score <= 100
        assert len(report.area_scores) > 0
    
    @pytest.mark.integration
    def test_assessment_includes_recommendations(
        self,
        sample_data_dir: Path,
    ) -> None:
        """Test that assessment generates recommendations."""
        report = run_assessment_from_csv(sample_data_dir)
        
        # Should have at least awareness of growth
        assert report.recommendations is not None
    
    @pytest.mark.integration
    def test_tenant_isolation(self, db_session) -> None:
        """Test that assessments are isolated by tenant."""
        from scalescore.repositories.assessment import AssessmentRepository
        
        repo = AssessmentRepository(db_session)
        
        # Create assessments for two tenants
        repo.save(
    org_id="org-a",
            assessment_id="assess-001",
            data={"score": 85},
        )
        repo.save(
    org_id="org-b",
            assessment_id="assess-002",
            data={"score": 72},
        )
        
        # Verify isolation
tenant_a_results = repo.list_all(org_id="org-a")
tenant_b_results = repo.list_all(org_id="org-b")
        
        assert len(tenant_a_results) == 1
        assert len(tenant_b_results) == 1
        assert tenant_a_results[0].assessment_id == "assess-001"
        assert tenant_b_results[0].assessment_id == "assess-002"
```

### E2E Test Example

```python
# tests/e2e/test_api_assessments.py
import pytest
from fastapi.testclient import TestClient


class TestAssessmentsAPI:
    """End-to-end API tests for assessments."""
    
    @pytest.mark.e2e
    def test_create_assessment(self, authenticated_client: TestClient) -> None:
        """Test creating an assessment via API."""
        response = authenticated_client.post(
            "/api/v1/assessments",
            json={
                "organization_id": "org-001",
                "organizations": [
                    {
                        "id": "org-001",
                        "name": "Test Org",
                        "headcount_current": 100,
                        "headcount_planned": 150,
                    }
                ],
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "overall_score" in data
        assert "area_scores" in data
    
    @pytest.mark.e2e
    def test_authentication_required(self, api_client: TestClient) -> None:
        """Test that endpoints require authentication."""
        response = api_client.get("/api/v1/assessments")
        
        assert response.status_code == 401
    
    @pytest.mark.e2e
    def test_health_endpoint(self, api_client: TestClient) -> None:
        """Test health endpoint is accessible."""
        response = api_client.get("/health")
        
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
```

### Performance Test Example

```python
# tests/performance/test_scoring_perf.py
import pytest
import time
from typing import Generator

from scalescore.scoring.engine import ScoringEngine
from scalescore.models.scaling import CapacityConstraint, GrowthSignal


class TestScoringPerformance:
    """Performance tests for scoring engine."""
    
    @pytest.fixture
    def engine(self) -> ScoringEngine:
        return ScoringEngine()
    
    @pytest.fixture
    def large_constraint_set(self) -> list[CapacityConstraint]:
        """Generate large set of constraints for performance testing."""
        return [
            CapacityConstraint(
                entity_id=f"entity-{i}",
                constraint_type="capacity",
                severity=["low", "medium", "high", "critical"][i % 4],
                current_utilization=0.5 + (i % 50) / 100,
                max_capacity=1000,
            )
            for i in range(1000)
        ]
    
    @pytest.mark.performance
    def test_scoring_1000_constraints_under_100ms(
        self,
        engine: ScoringEngine,
        large_constraint_set: list[CapacityConstraint],
    ) -> None:
        """Verify scoring 1000 constraints completes in <100ms."""
        start = time.perf_counter()
        
        result = engine.calculate_area_score(
            area="operations",
            constraints=large_constraint_set,
            growth_signals=[],
        )
        
        duration_ms = (time.perf_counter() - start) * 1000
        
        assert duration_ms < 100, f"Scoring took {duration_ms:.2f}ms, expected <100ms"
        assert result.constraint_count == 1000
    
    @pytest.mark.performance
    def test_full_assessment_10_entities_under_500ms(
        self,
        engine: ScoringEngine,
    ) -> None:
        """Verify full assessment with 10 entities completes in <500ms."""
        from tests.factories.organization import AssessmentFactory
        
        data = AssessmentFactory.create_full_dataset()
        
        start = time.perf_counter()
        
        from scalescore.assessment import run_assessment
        result = run_assessment(data)
        
        duration_ms = (time.perf_counter() - start) * 1000
        
        assert duration_ms < 500, f"Assessment took {duration_ms:.2f}ms"
```

### CI/CD Integration

```yaml
# .github/workflows/test.yml
name: Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      
      - name: Install dependencies
        run: pip install -e ".[dev]"
      
      - name: Run unit tests
        run: pytest tests/unit -v --tb=short -m unit
      
      - name: Upload coverage
        uses: codecov/codecov-action@v4

  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: scalescore_test
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
    
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      
      - name: Install dependencies
        run: pip install -e ".[dev]"
      
      - name: Run integration tests
        run: pytest tests/integration -v -m integration
        env:
          DB_HOST: localhost
          DB_PASSWORD: test

  e2e-tests:
    runs-on: ubuntu-latest
    needs: [unit-tests, integration-tests]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      
      - name: Install dependencies
        run: pip install -e ".[dev]"
      
      - name: Run E2E tests
        run: pytest tests/e2e -v -m e2e
```

### Coverage Requirements

| Module | Minimum Coverage |
|--------|-----------------|
| `scoring/` | 90% |
| `models/` | 85% |
| `core/` | 85% |
| `api/` | 80% |
| `connectors/` | 75% |
| **Overall** | **80%** |

## Related Decisions

- ADR-0007: Error Handling Strategy (testing error paths)
- ADR-0010: Structured Logging and Observability (test logging)
- ADR-0012: Background Job Processing (testing async tasks)

## Notes

- Run unit tests locally before every commit
- Integration tests run in CI on every PR
- Performance tests run nightly to detect regressions
- Consider property-based testing with Hypothesis for scoring edge cases
- Add mutation testing with mutmut after reaching 80% coverage
