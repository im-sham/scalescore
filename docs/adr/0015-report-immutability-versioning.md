# ADR-0015: Report Immutability and Versioning

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore generates assessment reports that:

- Capture point-in-time snapshots of organizational readiness
- Are used for historical analysis and trend tracking
- May be shared externally (board reports, audits, compliance)
- Must remain consistent even as scoring algorithms evolve

Current implementation includes:
- `report_version: str = "1.0"` in ScaleScoreReport
- `assessment_version: str = "1.0"` in ReadinessScore
- No formal versioning strategy or migration path

Questions that need answering:
- What happens when we change the report schema?
- How do we maintain backward compatibility?
- Can old reports be recalculated with new algorithms?
- How do we handle algorithm version vs. schema version?

## Decision Drivers

- **Auditability**: Historical reports must remain accessible and interpretable
- **Comparability**: Users need to compare scores over time
- **Evolution**: Algorithms and schemas will change
- **Compliance**: SOC2 requires data integrity and retention
- **API Stability**: Clients depend on consistent response formats

## Considered Options

### Option 1: Immutable Reports with Embedded Version

Reports are immutable once created. Version information embedded in report.

**Pros:**
- Simple implementation
- Historical consistency guaranteed
- No migration complexity
- Clear audit trail

**Cons:**
- Cannot retroactively fix bugs in reports
- Storage grows over time
- Different versions may confuse users

### Option 2: Report Regeneration on Access

Store raw data, regenerate reports on access with latest algorithm.

**Pros:**
- Always consistent with current algorithm
- Smaller storage (just raw data)
- Bug fixes apply retroactively

**Cons:**
- Historical scores change (violates auditability)
- Performance overhead on access
- Cannot reproduce historical reports

### Option 3: Dual Storage (Immutable + Regeneratable)

Store both immutable reports and raw data for optional regeneration.

**Pros:**
- Best of both worlds
- Can compare old vs. new calculations
- Flexibility for different use cases

**Cons:**
- Storage overhead
- Complexity in implementation
- Must maintain both paths

### Option 4: Event Sourcing

Store events (input data + algorithm version), derive reports.

**Pros:**
- Complete history
- Can replay with any algorithm version
- Maximum flexibility

**Cons:**
- Significant complexity
- Overkill for current needs
- Longer development time

## Decision

**Use Option 1: Immutable Reports with Embedded Version, with clear versioning strategy.**

We will implement:
1. **Immutable Reports**: Once generated, reports never change
2. **Embedded Versioning**: Report includes both schema and algorithm versions
3. **Semantic Versioning**: MAJOR.MINOR for both versions
4. **Backward Compatibility**: New clients read old report versions
5. **Optional Recalculation**: Users can explicitly request new calculation

Rationale:
- Immutability provides audit trail required for SOC2
- Embedded versions enable correct interpretation
- Simplicity aligns with current project phase
- Optional recalculation provides escape hatch when needed

## Consequences

### Positive
- Historical reports are preserved exactly as generated
- Clear audit trail for compliance
- Simple implementation and mental model
- Users can trust report consistency
- Comparison across time is meaningful

### Negative
- Cannot fix bugs in historical reports
- Storage grows with report history
- Must maintain schema compatibility readers

### Neutral
- Version information adds to report size
- Documentation needed for version differences

## Implementation Notes

### Version Schema

```python
# src/scalescore/models/scaling.py
from datetime import datetime
from pydantic import BaseModel, Field


class ReportMetadata(BaseModel):
    """Metadata for report versioning and traceability."""
    
    # Schema version (report structure)
    # MAJOR: Breaking changes to report structure
    # MINOR: Additive changes (new fields)
    schema_version: str = "1.0"
    
    # Algorithm version (scoring logic)
    # MAJOR: Significant changes to scoring methodology
    # MINOR: Tweaks to weights, thresholds, etc.
    algorithm_version: str = "1.0"
    
    # Generation metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = "scalescore"
    
    # Traceability
    assessment_id: str
    org_id: str
    input_hash: str  # Hash of input data for verification
    
    # Immutability marker
    is_final: bool = True  # False only for draft/preview reports


class ScaleScoreReport(BaseModel):
    """Complete assessment report - immutable after generation."""
    
    # Report identification
    id: str
    organization_id: str
    
    # Versioning and metadata
    metadata: ReportMetadata
    
    # Legacy fields for backward compatibility
    report_version: str = Field(
        default="1.0",
        description="Deprecated: Use metadata.schema_version",
        deprecated=True,
    )
    assessment_version: str = Field(
        default="1.0",
        description="Deprecated: Use metadata.algorithm_version",
        deprecated=True,
    )
    
    # Report content
    overall_score: float = Field(ge=0, le=100)
    area_scores: list[ReadinessScore]
    bottlenecks: list[Bottleneck]
    recommendations: list[Recommendation]
    
    # Summary for quick access
    summary: ReportSummary
    
    model_config = ConfigDict(
        # Prevent modification after creation
        frozen=True,
    )
    
    def __init__(self, **data):
        # Sync legacy fields with metadata
        if "metadata" in data:
            data["report_version"] = data["metadata"]["schema_version"]
            data["assessment_version"] = data["metadata"]["algorithm_version"]
        super().__init__(**data)
```

### Version Compatibility

```python
# src/scalescore/core/version_compat.py
from typing import Any, Callable
from packaging import version

from scalescore.models.scaling import ScaleScoreReport


# Registry of schema migrations
SCHEMA_MIGRATIONS: dict[str, Callable[[dict], dict]] = {}


def register_migration(from_version: str, to_version: str):
    """Decorator to register a schema migration."""
    def decorator(func: Callable[[dict], dict]):
        SCHEMA_MIGRATIONS[f"{from_version}->{to_version}"] = func
        return func
    return decorator


@register_migration("1.0", "1.1")
def migrate_1_0_to_1_1(data: dict) -> dict:
    """
    Migration from schema 1.0 to 1.1.
    
    Changes:
    - Added 'summary' field
    - Moved 'generated_at' to metadata
    """
    # Add default summary if missing
    if "summary" not in data:
        data["summary"] = {
            "total_constraints": len(data.get("bottlenecks", [])),
            "critical_count": sum(
                1 for b in data.get("bottlenecks", [])
                if b.get("severity") == "critical"
            ),
            "top_recommendation": (
                data["recommendations"][0]["title"]
                if data.get("recommendations")
                else None
            ),
        }
    
    # Migrate timestamp to metadata
    if "generated_at" in data and "metadata" not in data:
        data["metadata"] = {
            "schema_version": "1.1",
            "algorithm_version": data.get("assessment_version", "1.0"),
            "generated_at": data.pop("generated_at"),
        }
    
    return data


class ReportReader:
    """Read reports of any version, migrating to current schema."""
    
    CURRENT_SCHEMA_VERSION = "1.1"
    
    def read(self, data: dict[str, Any]) -> ScaleScoreReport:
        """
        Read report data, migrating if necessary.
        
        Args:
            data: Raw report data (from storage)
            
        Returns:
            Report in current schema version
        """
        # Determine source version
        source_version = self._get_schema_version(data)
        
        # Migrate if needed
        if source_version != self.CURRENT_SCHEMA_VERSION:
            data = self._migrate(data, source_version)
        
        return ScaleScoreReport(**data)
    
    def _get_schema_version(self, data: dict) -> str:
        """Extract schema version from report data."""
        if "metadata" in data:
            return data["metadata"].get("schema_version", "1.0")
        return data.get("report_version", "1.0")
    
    def _migrate(
        self,
        data: dict,
        from_version: str,
    ) -> dict:
        """Apply migrations to reach current version."""
        current = from_version
        
        while current != self.CURRENT_SCHEMA_VERSION:
            # Find next migration
            next_version = self._get_next_version(current)
            migration_key = f"{current}->{next_version}"
            
            if migration_key not in SCHEMA_MIGRATIONS:
                raise ValueError(
                    f"No migration path from {current} to {self.CURRENT_SCHEMA_VERSION}"
                )
            
            # Apply migration
            data = SCHEMA_MIGRATIONS[migration_key](data)
            current = next_version
        
        return data
    
    def _get_next_version(self, current: str) -> str:
        """Get the next version in migration path."""
        # Simple increment for now
        major, minor = current.split(".")
        return f"{major}.{int(minor) + 1}"
```

### Input Hashing for Verification

```python
# src/scalescore/core/hashing.py
import hashlib
import json
from typing import Any


def hash_assessment_input(data: dict[str, Any]) -> str:
    """
    Create deterministic hash of assessment input.
    
    Used to verify that a report was generated from specific input data.
    """
    # Normalize data for consistent hashing
    normalized = _normalize_for_hash(data)
    
    # Create JSON string with sorted keys
    json_str = json.dumps(normalized, sort_keys=True, default=str)
    
    # Return SHA-256 hash
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]


def _normalize_for_hash(data: Any) -> Any:
    """Normalize data for consistent hashing."""
    if isinstance(data, dict):
        return {k: _normalize_for_hash(v) for k, v in sorted(data.items())}
    elif isinstance(data, list):
        return [_normalize_for_hash(item) for item in data]
    elif isinstance(data, float):
        # Round floats to avoid precision issues
        return round(data, 6)
    return data


def verify_report_input(
    report: "ScaleScoreReport",
    input_data: dict[str, Any],
) -> bool:
    """Verify that a report was generated from the given input."""
    expected_hash = hash_assessment_input(input_data)
    return report.metadata.input_hash == expected_hash
```

### Report Repository

```python
# src/scalescore/repositories/report.py
from datetime import datetime
from typing import Optional
import json

from sqlalchemy.orm import Session

from scalescore.models.scaling import ScaleScoreReport, ReportMetadata
from scalescore.core.version_compat import ReportReader


class ReportRepository:
    """Repository for storing and retrieving immutable reports."""
    
    def __init__(self, session: Session):
        self.session = session
        self.reader = ReportReader()
    
    def save(
        self,
        report: ScaleScoreReport,
        org_id: str,
    ) -> str:
        """
        Save a report. Reports are immutable - saving the same ID fails.
        """
        # Check if report already exists
        existing = self._get_raw(report.id, org_id)
        if existing:
            raise ValueError(f"Report {report.id} already exists (immutable)")
        
        # Store as JSON blob with version info
        record = ReportRecord(
            id=report.id,
            org_id=org_id,
            organization_id=report.organization_id,
            schema_version=report.metadata.schema_version,
            algorithm_version=report.metadata.algorithm_version,
            generated_at=report.metadata.generated_at,
            overall_score=report.overall_score,
            data=report.model_dump_json(),
        )
        
        self.session.add(record)
        self.session.commit()
        
        return report.id
    
    def get(
        self,
        report_id: str,
        org_id: str,
    ) -> Optional[ScaleScoreReport]:
        """
        Get a report, migrating schema if necessary.
        """
        raw = self._get_raw(report_id, org_id)
        if not raw:
            return None
        
        # Parse and migrate if needed
        data = json.loads(raw.data)
        return self.reader.read(data)
    
    def _get_raw(
        self,
        report_id: str,
        org_id: str,
    ) -> Optional["ReportRecord"]:
        """Get raw report record from database."""
        return (
            self.session.query(ReportRecord)
            .filter(
                ReportRecord.id == report_id,
                ReportRecord.org_id == org_id,
            )
            .first()
        )
    
    def list_reports(
        self,
        org_id: str,
        organization_id: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[ScaleScoreReport]:
        """List reports with optional filters."""
        query = (
            self.session.query(ReportRecord)
            .filter(ReportRecord.org_id == org_id)
        )
        
        if organization_id:
            query = query.filter(ReportRecord.organization_id == organization_id)
        if from_date:
            query = query.filter(ReportRecord.generated_at >= from_date)
        if to_date:
            query = query.filter(ReportRecord.generated_at <= to_date)
        
        query = query.order_by(ReportRecord.generated_at.desc()).limit(limit)
        
        return [
            self.reader.read(json.loads(record.data))
            for record in query.all()
        ]
    
    def get_report_history(
        self,
        org_id: str,
        organization_id: str,
        limit: int = 12,
    ) -> list[dict]:
        """Get historical scores for trend analysis."""
        reports = self.list_reports(
            org_id=org_id,
            organization_id=organization_id,
            limit=limit,
        )
        
        return [
            {
                "report_id": r.id,
                "generated_at": r.metadata.generated_at,
                "overall_score": r.overall_score,
                "algorithm_version": r.metadata.algorithm_version,
            }
            for r in reports
        ]
```

### Algorithm Version Registry

```python
# src/scalescore/scoring/versions.py
from dataclasses import dataclass
from datetime import date
from typing import Callable, Any


@dataclass
class AlgorithmVersion:
    """Describes a scoring algorithm version."""
    version: str
    release_date: date
    description: str
    changes: list[str]
    is_current: bool = False


# Track algorithm versions
ALGORITHM_VERSIONS = [
    AlgorithmVersion(
        version="1.0",
        release_date=date(2026, 1, 15),
        description="Initial scoring algorithm",
        changes=[
            "Base constraint-based scoring",
            "Severity-weighted penalties",
            "Growth signal adjustments",
        ],
        is_current=True,
    ),
    # Future versions will be added here
]


def get_current_algorithm_version() -> str:
    """Get the current algorithm version."""
    for v in ALGORITHM_VERSIONS:
        if v.is_current:
            return v.version
    return ALGORITHM_VERSIONS[-1].version


def get_algorithm_info(version: str) -> AlgorithmVersion | None:
    """Get information about a specific algorithm version."""
    for v in ALGORITHM_VERSIONS:
        if v.version == version:
            return v
    return None
```

### Recalculation Service

```python
# src/scalescore/services/recalculation.py
from scalescore.models.scaling import ScaleScoreReport
from scalescore.scoring.engine import ScoringEngine
from scalescore.scoring.versions import get_current_algorithm_version


class RecalculationService:
    """Service for recalculating reports with current algorithm."""
    
    def __init__(self, scoring_engine: ScoringEngine):
        self.engine = scoring_engine
    
    def recalculate(
        self,
        original_report: ScaleScoreReport,
        input_data: dict,
    ) -> tuple[ScaleScoreReport, "ComparisonResult"]:
        """
        Recalculate a report with current algorithm.
        
        Returns:
            Tuple of (new_report, comparison_with_original)
        """
        # Generate new report with current algorithm
        new_report = self.engine.generate_report(
            input_data,
            algorithm_version=get_current_algorithm_version(),
        )
        
        # Compare with original
        comparison = self._compare_reports(original_report, new_report)
        
        return new_report, comparison
    
    def _compare_reports(
        self,
        original: ScaleScoreReport,
        recalculated: ScaleScoreReport,
    ) -> "ComparisonResult":
        """Compare two reports and highlight differences."""
        return ComparisonResult(
            original_version=original.metadata.algorithm_version,
            new_version=recalculated.metadata.algorithm_version,
            score_delta=recalculated.overall_score - original.overall_score,
            area_deltas={
                area.area: (
                    recalculated.area_scores[i].score - area.score
                )
                for i, area in enumerate(original.area_scores)
            },
            new_bottlenecks=[
                b for b in recalculated.bottlenecks
                if b not in original.bottlenecks
            ],
            resolved_bottlenecks=[
                b for b in original.bottlenecks
                if b not in recalculated.bottlenecks
            ],
        )


@dataclass
class ComparisonResult:
    """Result of comparing two report versions."""
    original_version: str
    new_version: str
    score_delta: float
    area_deltas: dict[str, float]
    new_bottlenecks: list
    resolved_bottlenecks: list
```

### API Endpoints

```python
# src/scalescore/api/v1/reports.py
from fastapi import APIRouter, Depends, Query

from scalescore.api.dependencies.auth import get_current_user, get_org_id
from scalescore.repositories.report import ReportRepository
from scalescore.services.recalculation import RecalculationService


router = APIRouter()


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    org_id: str = Depends(get_org_id),
    include_version_info: bool = Query(False),
) -> ScaleScoreReport:
    """Get an immutable report by ID."""
    repo = ReportRepository(get_db())
    report = repo.get(report_id, org_id)
    
    if not report:
        raise HTTPException(404, "Report not found")
    
    return report


@router.get("/reports/{report_id}/version-info")
async def get_report_version_info(
    report_id: str,
    org_id: str = Depends(get_org_id),
) -> dict:
    """Get version information for a report."""
    repo = ReportRepository(get_db())
    report = repo.get(report_id, org_id)
    
    if not report:
        raise HTTPException(404, "Report not found")
    
    current_algo = get_current_algorithm_version()
    
    return {
        "report_id": report_id,
        "schema_version": report.metadata.schema_version,
        "algorithm_version": report.metadata.algorithm_version,
        "current_algorithm_version": current_algo,
        "is_outdated": report.metadata.algorithm_version != current_algo,
        "generated_at": report.metadata.generated_at,
    }


@router.post("/reports/{report_id}/recalculate")
async def recalculate_report(
    report_id: str,
    org_id: str = Depends(get_org_id),
) -> dict:
    """
    Recalculate a report with current algorithm.
    
    Original report remains unchanged. Returns comparison.
    """
    repo = ReportRepository(get_db())
    original = repo.get(report_id, org_id)
    
    if not original:
        raise HTTPException(404, "Report not found")
    
    # Get original input data
    input_data = get_input_data_for_report(report_id, org_id)
    
    # Recalculate
    service = RecalculationService(ScoringEngine())
    new_report, comparison = service.recalculate(original, input_data)
    
    # Save new report (it's a new immutable report)
    repo.save(new_report, org_id)
    
    return {
        "original_report_id": report_id,
        "new_report_id": new_report.id,
        "comparison": comparison,
    }
```

## Related Decisions

- ADR-0003: Constraint-Based Scoring (algorithm versioning)
- ADR-0006: PostgreSQL as Primary Database (report storage)
- ADR-0008: API Versioning Strategy (schema versioning alignment)

## Notes

- Consider archival strategy for old reports (cold storage after 1 year)
- Document version changes in changelog for users
- Add report export feature for compliance (PDF with version watermark)
- Consider adding "rehydrate" endpoint to regenerate reports from stored inputs
