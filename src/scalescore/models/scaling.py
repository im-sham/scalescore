"""
Workflow-first AI operational readiness models for ScaleScore.

These models represent growth signals, constraints, risks, workflow context,
and the readiness scores that are the primary outputs of ScaleScore.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    """Risk severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConstraintType(StrEnum):
    """Types of scaling constraints."""

    CAPACITY = "capacity"  # System/facility capacity limits
    DEPENDENCY = "dependency"  # Vendor/system dependencies
    GOVERNANCE = "governance"  # Process/compliance gaps
    FINANCIAL = "financial"  # Budget/runway constraints
    TALENT = "talent"  # Hiring/skill gaps
    TIMELINE = "timeline"  # Schedule conflicts


class FunctionalArea(StrEnum):
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


class AssessmentMode(StrEnum):
    """Primary assessment framing."""

    ORGANIZATION = "organization"
    WORKFLOW = "workflow"


class WorkflowBlastRadius(StrEnum):
    """Potential impact of workflow failure or misalignment."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkflowReadinessPillar(StrEnum):
    """Workflow-first readiness pillars for AI-enabled operations."""

    WORKFLOW_STABILITY = "workflow_stability"
    SYSTEM_AND_DEPENDENCY_RESILIENCE = "system_and_dependency_resilience"
    HUMAN_OVERSIGHT_AND_OWNERSHIP = "human_oversight_and_ownership"
    CONTROL_AND_EVIDENCE_READINESS = "control_and_evidence_readiness"
    AUTOMATION_FIT_AND_BLAST_RADIUS = "automation_fit_and_blast_radius"


class WorkflowAssessmentContext(BaseModel):
    """Metadata required to score an AI-enabled workflow."""

    workflow_id: str
    name: str
    business_function: str
    owner: str
    ai_role: str
    systems_touched: list[str]
    human_escalation_path: list[str]
    control_requirements: list[str]
    blast_radius: WorkflowBlastRadius
    description: str = ""
    fallback_mode: str = ""
    override_rights: list[str] = Field(default_factory=list)
    error_tolerance: str = ""
    reversibility: str = ""


class WorkflowEvidenceInput(BaseModel):
    """Optional structured evidence signals for direct workflow submissions."""

    owner_confirmed: bool | None = None
    systems_verified: bool | None = None
    escalation_tested: bool | None = None
    fallback_tested: bool | None = None
    override_reviewed: bool | None = None
    approval_evidence_count: int | None = Field(default=None, ge=0)
    decision_log_count: int | None = Field(default=None, ge=0)
    rollback_tested: bool | None = None


class WorkflowPillarScore(BaseModel):
    """Score and rationale for a single workflow readiness pillar."""

    pillar: WorkflowReadinessPillar
    score: float
    grade: str = ""
    rationale: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class OrgWorkflowRollup(BaseModel):
    """Organization-level rollup derived from workflow readiness reports."""

    org_id: str
    workflow_count: int = 0
    rollup_method: str = "mean_workflow_score"
    workflow_ids: list[str] = Field(default_factory=list)
    report_ids: list[str] = Field(default_factory=list)
    average_workflow_score: float = 0.0
    overall_grade: str = ""
    lowest_workflow_score: float | None = None
    highest_workflow_score: float | None = None
    total_critical_risks: int = 0
    note: str = ""


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

    This is the primary organization-level score that ScaleScore produces
    in compatibility mode - a 0-100 measure of how prepared an area is for
    operational change and scale.
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


class ScoreHistoryTrendWindow(BaseModel):
    """Trend summary for a fixed lookback window."""

    days: int
    delta: float | None = None
    direction: str | None = None
    compared_report_id: str | None = None


class ScoreHistoryComparison(BaseModel):
    """Comparison between the latest and previous assessment snapshots."""

    current_report_id: str | None = None
    previous_report_id: str | None = None
    score_delta: float | None = None
    risk_delta: int | None = None
    critical_risk_delta: int | None = None
    generated_at_delta_hours: float | None = None


class ScoreHistoryResponse(BaseModel):
    """Response model for organization score-history timelines."""

    org_id: str
    points: list[ScoreHistoryPoint] = Field(default_factory=list)
    count: int = 0
    trend_7d: ScoreHistoryTrendWindow = Field(default_factory=lambda: ScoreHistoryTrendWindow(days=7))
    trend_30d: ScoreHistoryTrendWindow = Field(default_factory=lambda: ScoreHistoryTrendWindow(days=30))
    trend_90d: ScoreHistoryTrendWindow = Field(default_factory=lambda: ScoreHistoryTrendWindow(days=90))
    comparison: ScoreHistoryComparison = Field(default_factory=ScoreHistoryComparison)


class ScaleScoreReport(BaseModel):
    """
    Complete assessment output - the full report produced by ScaleScore.

    This is the primary deliverable that contains all scores, risks,
    constraints, and recommendations for an organization or workflow.
    """

    # Report identity
    report_id: str
    org_id: str
    org_name: str = ""
    assessment_mode: AssessmentMode = AssessmentMode.ORGANIZATION

    # Generation metadata
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    report_version: str = "1.1"
    assessment_period_start: datetime | None = None
    assessment_period_end: datetime | None = None

    # Overall score
    overall_score: float  # 0-100, weighted average of area scores
    overall_grade: str = ""
    overall_trend: str = "stable"

    # Area breakdowns
    area_scores: list[ReadinessScore] = Field(default_factory=list)

    # Workflow-first assessment context
    workflow_context: WorkflowAssessmentContext | None = None
    workflow_readiness_score: float | None = None
    workflow_readiness_grade: str | None = None
    workflow_pillar_scores: list[WorkflowPillarScore] = Field(default_factory=list)
    top_trust_gaps: list[str] = Field(default_factory=list)
    prioritized_remediation_actions: list[str] = Field(default_factory=list)
    org_rollup: OrgWorkflowRollup | None = None

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
