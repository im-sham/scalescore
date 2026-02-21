"""
Scaling-specific models for ScaleScore.

These models represent growth signals, constraints, risks, and
the readiness scores that are the primary output of ScaleScore.
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Risk severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConstraintType(str, Enum):
    """Types of scaling constraints."""

    CAPACITY = "capacity"  # System/facility capacity limits
    DEPENDENCY = "dependency"  # Vendor/system dependencies
    GOVERNANCE = "governance"  # Process/compliance gaps
    FINANCIAL = "financial"  # Budget/runway constraints
    TALENT = "talent"  # Hiring/skill gaps
    TIMELINE = "timeline"  # Schedule conflicts


class FunctionalArea(str, Enum):
    """Organizational functional areas for scoring."""

    ENGINEERING = "engineering"
    SALES = "sales"
    OPERATIONS = "operations"
    FINANCE = "finance"
    PEOPLE = "people"
    FACILITIES = "facilities"
    LEGAL_COMPLIANCE = "legal_compliance"
    PRODUCT = "product"
    CUSTOMER_SUCCESS = "customer_success"
    MARKETING = "marketing"


class GrowthSignal(BaseModel):
    """
    Indicator of planned growth that drives capacity requirements.

    Growth signals represent the "demand side" of scaling - what
    the organization is planning to do that will stress its capacity.
    """

    id: str
    org_id: str

    # Signal details
    signal_type: str  # headcount_plan, revenue_target, product_launch, market_expansion, etc.
    title: str = ""
    description: str = ""

    # Timeline
    target_date: datetime
    duration_days: int | None = None  # For ongoing initiatives

    # Magnitude
    magnitude: float  # % increase or absolute value depending on type
    magnitude_type: str = "percentage"  # percentage, absolute
    baseline_value: float | None = None

    # Confidence and source
    confidence: float = 0.8  # 0.0 to 1.0 - how certain is this signal
    source: str = ""  # plan document, exec input, board deck, etc.
    owner: str = ""  # Who owns this initiative

    # Impact mapping
    affected_areas: list[FunctionalArea] = Field(default_factory=list)

    # Status
    status: str = "planned"  # planned, approved, in_progress, completed, cancelled

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CapacityConstraint(BaseModel):
    """
    A limit that could block scaling if not addressed.

    Constraints are the "supply side" problems - where the organization
    lacks capacity to support planned growth.
    """

    id: str
    org_id: str

    # What's constrained
    entity_id: str  # Reference to System, Facility, Team, Vendor, etc.
    entity_type: str
    entity_name: str = ""

    # Constraint classification
    constraint_type: ConstraintType
    title: str = ""
    description: str = ""

    # Current state
    current_utilization: float  # 0.0 to 1.0
    current_value: float | None = None
    max_value: float | None = None
    unit: str = ""

    # Projection
    projected_utilization: float | None = None
    projected_breach_date: datetime | None = None
    breach_probability: float = 0.0  # 0.0 to 1.0

    # Related growth signals
    triggered_by: list[str] = Field(default_factory=list)  # growth_signal_ids

    # Mitigation
    mitigation_options: list[str] = Field(default_factory=list)
    mitigation_effort: str = ""  # low, medium, high
    mitigation_cost: float | None = None
    mitigation_time_days: int | None = None

    # Status
    status: str = "identified"  # identified, acknowledged, mitigating, resolved
    owner: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RiskIndicator(BaseModel):
    """
    A specific identified risk with scoring and recommendations.

    Risks are derived from constraints and their potential business impact.
    This is the primary "finding" that ScaleScore surfaces to users.
    """

    id: str
    org_id: str

    # Risk details
    title: str
    description: str
    risk_level: RiskLevel

    # Classification
    functional_area: FunctionalArea
    constraint_type: ConstraintType
    category: str = ""  # More specific categorization

    # Affected entities
    affected_entities: list[str] = Field(default_factory=list)  # entity_ids
    related_constraints: list[str] = Field(default_factory=list)  # constraint_ids

    # Scoring
    probability: float = 0.5  # 0.0 to 1.0 - likelihood of occurring
    impact_score: float = 0.5  # 0.0 to 1.0 - severity if it occurs
    risk_score: float = 0.0  # Calculated: probability × impact × severity_multiplier

    # Timeline
    projected_impact_date: datetime | None = None
    time_to_impact_days: int | None = None

    # Recommendations
    recommendations: list[str] = Field(default_factory=list)
    primary_recommendation: str = ""

    # Evidence
    evidence: list[str] = Field(default_factory=list)  # Data points supporting this risk

    # Status
    status: str = "open"  # open, acknowledged, mitigating, accepted, resolved
    owner: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReadinessScore(BaseModel):
    """
    Aggregate readiness score for a functional area.

    This is the primary "score" that ScaleScore produces - a 0-100
    measure of how prepared an area is for planned growth.
    """

    org_id: str
    functional_area: FunctionalArea

    # The score
    score: float  # 0-100
    grade: str = ""  # A, B, C, D, F (derived from score)

    # Score breakdown
    sub_scores: dict[str, float] = Field(default_factory=dict)

    # What's affecting this score
    constraints: list[str] = Field(default_factory=list)  # constraint_ids
    risks: list[str] = Field(default_factory=list)  # risk_ids
    constraint_count: int = 0
    risk_count: int = 0
    critical_risk_count: int = 0

    # Trend
    trend: str = "stable"  # improving, stable, declining
    score_7d_ago: float | None = None
    score_30d_ago: float | None = None

    # Assessment metadata
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    assessment_version: str = "1.0"

    def calculate_grade(self) -> str:
        """Derive letter grade from score."""
        if self.score >= 90:
            return "A"
        elif self.score >= 80:
            return "B"
        elif self.score >= 70:
            return "C"
        elif self.score >= 60:
            return "D"
        else:
            return "F"


class Recommendation(BaseModel):
    """
    An actionable recommendation to address risks or constraints.
    """

    id: str
    org_id: str

    # Recommendation details
    title: str
    description: str
    recommendation_type: str  # expand_capacity, add_redundancy, accelerate_hiring, etc.

    # What it addresses
    target_entity_id: str
    target_entity_type: str
    addresses_risks: list[str] = Field(default_factory=list)  # risk_ids
    addresses_constraints: list[str] = Field(default_factory=list)  # constraint_ids

    # Effort/Impact assessment
    effort: str  # low, medium, high
    impact: str  # low, medium, high
    priority_score: float = 0.0  # Calculated based on impact/effort ratio

    # Estimates
    estimated_cost: float | None = None
    estimated_time_days: int | None = None

    # Status
    status: str = "proposed"  # proposed, accepted, in_progress, completed, rejected
    owner: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScoreHistoryPoint(BaseModel):
    """Point-in-time readiness snapshot for trend timelines."""

    report_id: str
    generated_at: datetime
    overall_score: float
    overall_grade: str
    overall_trend: str
    total_risks: int
    critical_risks: int
    high_risks: int


class ScoreHistoryResponse(BaseModel):
    """Response model for organization score-history timelines."""

    org_id: str
    points: list[ScoreHistoryPoint] = Field(default_factory=list)
    count: int = 0


class ScaleScoreReport(BaseModel):
    """
    Complete assessment output - the full report produced by ScaleScore.

    This is the primary deliverable that contains all scores, risks,
    constraints, and recommendations for an organization.
    """

    # Report identity
    report_id: str
    org_id: str
    org_name: str = ""

    # Generation metadata
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    report_version: str = "1.0"
    assessment_period_start: datetime | None = None
    assessment_period_end: datetime | None = None

    # Overall score
    overall_score: float  # 0-100, weighted average of area scores
    overall_grade: str = ""
    overall_trend: str = "stable"

    # Area breakdowns
    area_scores: list[ReadinessScore] = Field(default_factory=list)

    # Findings
    top_risks: list[RiskIndicator] = Field(default_factory=list)
    constraints: list[CapacityConstraint] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)

    # Inputs used
    growth_signals: list[GrowthSignal] = Field(default_factory=list)

    # Summary statistics
    total_risks: int = 0
    critical_risks: int = 0
    high_risks: int = 0
    total_constraints: int = 0
    total_recommendations: int = 0

    # Executive summary (can be AI-generated)
    executive_summary: str = ""
    key_findings: list[str] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)
