"""
Workflow-first AI operational readiness models for ScaleScore.

These models represent growth signals, constraints, risks, workflow context,
and the readiness scores that are the primary outputs of ScaleScore.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

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


class WorkflowControlStatus(StrEnum):
    """Explicit maturity state for a workflow control area."""

    MISSING = "missing"
    DOCUMENTED = "documented"
    OPERATING = "operating"
    VERIFIED = "verified"


ProofhouseCachePolicy = Literal[
    "ref_only",
    "summary_snapshot",
    "digest_snapshot",
    "owner_dereference_required",
]


class WorkflowRef(BaseModel):
    """Canonical workflow reference emitted by Workflow Context."""

    ref_id: str
    ref_type: Literal["workflow"] = "workflow"
    source_capability: Literal["workflow_context"] = "workflow_context"
    organization_id: str
    environment_id: str = "production"
    external_uri: str | None = None
    snapshot_id: str | None = None
    version: str | None = None
    created_at: datetime | str
    updated_at: datetime | str
    summary: str
    workflow_id: str
    title: str
    subject_type: str
    subject_key: str | None = None
    owner: str | None = None
    review_status: str


class WorkflowRefEnvelope(BaseModel):
    """Proofhouse V0.1 envelope for Workflow Context refs."""

    contract_version: Literal["proofhouse-shared-contracts/v0.1"] = (
        "proofhouse-shared-contracts/v0.1"
    )
    contract_name: Literal["WorkflowRef"] = "WorkflowRef"
    producer_capability: Literal["workflow_context"] = "workflow_context"
    producer_system: Literal["proofhouse-workflow-context"] = (
        "proofhouse-workflow-context"
    )
    canonical_owner: Literal["workflow_context"] = "workflow_context"
    issued_at: datetime | str
    cache_policy: ProofhouseCachePolicy = "summary_snapshot"
    ref: WorkflowRef


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


class WorkflowControlCoverageInput(BaseModel):
    """Explicit maturity for core workflow control areas."""

    approval_gate: WorkflowControlStatus | None = None
    decision_logging: WorkflowControlStatus | None = None
    evidence_retention: WorkflowControlStatus | None = None
    exception_handling: WorkflowControlStatus | None = None
    periodic_review: WorkflowControlStatus | None = None


class WorkflowEvidencePostureInput(BaseModel):
    """Evidence completeness and freshness for a workflow submission."""

    control_evidence_coverage_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    freshest_evidence_age_days: int | None = Field(default=None, ge=0)
    audit_trail_complete: bool | None = None
    linked_artifacts: bool | None = None


class WorkflowEvidenceInput(BaseModel):
    """Optional structured evidence signals for direct workflow submissions."""

    control_coverage: WorkflowControlCoverageInput | None = None
    evidence_posture: WorkflowEvidencePostureInput | None = None
    owner_confirmed: bool | None = None
    systems_verified: bool | None = None
    escalation_tested: bool | None = None
    fallback_tested: bool | None = None
    override_reviewed: bool | None = None
    approval_evidence_count: int | None = Field(default=None, ge=0)
    decision_log_count: int | None = Field(default=None, ge=0)
    rollback_tested: bool | None = None


class OperationalLearningSuitabilityStatus(StrEnum):
    """Suitability status for operational-learning candidate evaluation."""

    EVAL_SUITABLE = "eval_suitable"
    TRAINING_CANDIDATE = "training_candidate"
    WEAK_CANDIDATE = "weak_candidate"
    BLOCKED = "blocked"
    UNSUITABLE = "unsuitable"


class OperationalLearningDimension(StrEnum):
    """Dimensions scored for operational-learning suitability."""

    REPEATABILITY = "repeatability"
    SOP_CLARITY = "sop_clarity"
    OUTCOME_OBSERVABILITY = "outcome_observability"
    REVIEW_DENSITY = "review_density"
    REDACTION_MANAGEABILITY = "redaction_manageability"
    GOVERNANCE_SAFETY = "governance_safety"


class OperationalLearningCompletenessState(StrEnum):
    """Completeness state for governance dependencies."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"


class OperationalLearningGovernanceStateStatus(StrEnum):
    """Normalized governance dependency posture for operational learning."""

    READY = "ready"
    PARTIAL = "partial"
    INCOMPLETE = "incomplete"
    HIGH_RISK = "high_risk"


class OperationalLearningGovernanceDependencyInput(BaseModel):
    """Optional governance dependency inputs from upstream workflow systems."""

    rights_completeness: OperationalLearningCompletenessState | None = None
    provenance_completeness: OperationalLearningCompletenessState | None = None
    redaction_readiness: OperationalLearningCompletenessState | None = None
    residual_risk_band: RiskLevel | None = None


class OperationalLearningInputs(BaseModel):
    """Optional upstream inputs for operational-learning candidate scoring."""

    sop_reference_present: bool | None = None
    sop_clarity_signal: float | None = Field(default=None, ge=0.0, le=100.0)
    outcome_spec_present: bool | None = None
    outcome_observability_signal: float | None = Field(default=None, ge=0.0, le=100.0)
    run_frequency_per_week: float | None = Field(default=None, ge=0.0)
    repeatability_signal: float | None = Field(default=None, ge=0.0, le=100.0)
    review_path_present: bool | None = None
    review_density_signal: float | None = Field(default=None, ge=0.0, le=100.0)
    redaction_manageability_signal: float | None = Field(default=None, ge=0.0, le=100.0)
    governance_dependency_state: OperationalLearningGovernanceDependencyInput | None = None


class OperationalLearningDimensionScore(BaseModel):
    """Score and rationale for a single operational-learning dimension."""

    dimension: OperationalLearningDimension
    score: float = Field(ge=0.0, le=100.0)
    rationale: str = ""


class OperationalLearningGovernanceDependencyState(BaseModel):
    """Normalized governance dependency posture for operational-learning use."""

    rights_completeness: OperationalLearningCompletenessState | None = None
    provenance_completeness: OperationalLearningCompletenessState | None = None
    redaction_readiness: OperationalLearningCompletenessState | None = None
    residual_risk_band: RiskLevel | None = None
    status: OperationalLearningGovernanceStateStatus = (
        OperationalLearningGovernanceStateStatus.INCOMPLETE
    )
    summary: str = ""


class OperationalLearningAssessmentResult(BaseModel):
    """Derived eval or internal-training suitability result."""

    score: float = Field(ge=0.0, le=100.0)
    status: OperationalLearningSuitabilityStatus
    threshold: float
    threshold_met: bool = False
    hard_blocked: bool = False


class OperationalLearningSuitabilitySummary(BaseModel):
    """Additive workflow suitability summary for operational learning."""

    status: OperationalLearningSuitabilityStatus
    dimension_scores: list[OperationalLearningDimensionScore] = Field(default_factory=list)
    eval_suitability: OperationalLearningAssessmentResult
    internal_training_candidacy: OperationalLearningAssessmentResult
    top_blockers: list[str] = Field(default_factory=list)
    top_reasons: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    governance_dependency_state: OperationalLearningGovernanceDependencyState = Field(
        default_factory=OperationalLearningGovernanceDependencyState
    )


class ClaimsReadinessState(StrEnum):
    """Synthetic claims readiness state supplied by upstream workflow systems."""

    READY = "ready"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REVIEW_REQUIRED = "review_required"
    UNVERIFIED = "unverified"
    MISSING = "missing"
    BLOCKED = "blocked"


class ClaimsSuitabilityStatus(StrEnum):
    """Readiness-owned claims suitability result."""

    EVAL_SUITABLE = "eval_suitable"
    WEAK_CANDIDATE = "weak_candidate"
    BLOCKED = "blocked"


class ClaimsWorkflowReadinessProfile(BaseModel):
    """Optional synthetic claims profile inputs on the document-operations path."""

    profile_id: str
    evidence_class_ids_present: list[str] = Field(default_factory=list)
    phi_boundary_review_state: ClaimsReadinessState | None = None
    redaction_review_state: ClaimsReadinessState | None = None
    rate_source_review_state: ClaimsReadinessState | None = None
    downstream_consistency_state: ClaimsReadinessState | None = None
    downstream_action_approval_state: ClaimsReadinessState | None = None
    savings_recognition_state: ClaimsReadinessState | None = None
    governance_claims_control_state: ClaimsReadinessState | None = None
    source_readiness_state: ClaimsReadinessState | None = None


class ClaimsSuitabilitySummary(BaseModel):
    """Additive claims suitability and trust-gap summary for Readiness reports."""

    profile_id: str
    status: ClaimsSuitabilityStatus
    score: float = Field(ge=0.0, le=100.0)
    top_blockers: list[str] = Field(default_factory=list)
    top_reasons: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    governance_dependency_state: str
    evidence_gap_state: str
    phi_redaction_state: str
    rate_source_traceability_state: str
    downstream_consistency_state: str
    savings_lifecycle_state: str


class DocumentOperationsReadinessProfile(BaseModel):
    """Document-operations summary signals consumed from Workflow Context snapshots."""

    fixture_id: str = "document_ops_regulated_review_v0"
    workflow_family: Literal["financial_services_document_review"] = (
        "financial_services_document_review"
    )
    subject_type: str = "document_packet"
    subject_key: str | None = None
    normal_case_id: str | None = None
    normal_case_state: str | None = None
    normal_case_closed_with_evidence: bool | None = None
    exception_case_id: str | None = None
    exception_case_state: str | None = None
    exception_case_escalated: bool | None = None
    exception_requires_compliance_signoff: bool | None = None
    redaction_review_required_before_internal_eval: bool | None = None
    sop_refs_present: bool | None = None
    outcome_refs_present: bool | None = None
    required_document_rules_present: bool | None = None
    evidence_refs_present: bool | None = None
    owner_confirmed: bool | None = None
    systems_verified: bool | None = None
    review_sla_defined: bool | None = None
    weekly_packet_volume: float | None = Field(default=None, ge=0.0)
    reviewed_case_count: int | None = Field(default=None, ge=0)
    source_evidence_ref_count: int | None = Field(default=None, ge=0)
    control_evidence_coverage_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    freshest_evidence_age_days: int | None = Field(default=None, ge=0)
    governance_dependency_state: OperationalLearningGovernanceDependencyInput | None = None
    claims_profile: ClaimsWorkflowReadinessProfile | None = None


class DocumentOperationsReadinessProjection(BaseModel):
    """Derived local scoring inputs for the document-operations proof path."""

    workflow_evidence: WorkflowEvidenceInput
    operational_learning_inputs: OperationalLearningInputs
    source_findings: list[str] = Field(default_factory=list)
    claims_suitability: ClaimsSuitabilitySummary | None = None


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


class AssessmentRef(BaseModel):
    """Compact Readiness-owned reference for downstream consumers."""

    ref_id: str
    ref_type: Literal["assessment"] = "assessment"
    source_capability: Literal["readiness"] = "readiness"
    organization_id: str
    environment_id: str = "production"
    external_uri: str | None = None
    snapshot_id: str | None = None
    version: str | None = None
    created_at: datetime
    summary: str
    assessment_id: str
    workflow_id: str | None = None
    workflow_ref: WorkflowRefEnvelope | None = None
    assessment_type: Literal[
        "workflow_readiness",
        "operational_learning_suitability",
    ] = "workflow_readiness"
    score: float | None = None
    grade: str | None = None
    status: str
    top_blockers: list[str] = Field(default_factory=list)
    top_reasons: list[str] = Field(default_factory=list)
    report_uri: str | None = None


class AssessmentRefEnvelope(BaseModel):
    """Proofhouse V0.1 envelope for Readiness assessment refs."""

    contract_version: Literal["proofhouse-shared-contracts/v0.1"] = (
        "proofhouse-shared-contracts/v0.1"
    )
    contract_name: Literal["AssessmentRef"] = "AssessmentRef"
    producer_capability: Literal["readiness"] = "readiness"
    producer_system: Literal["proofhouse-readiness"] = "proofhouse-readiness"
    canonical_owner: Literal["readiness"] = "readiness"
    issued_at: datetime
    cache_policy: ProofhouseCachePolicy = "summary_snapshot"
    ref: AssessmentRef


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
    workflow_ref: WorkflowRefEnvelope | None = None
    assessment_ref: AssessmentRefEnvelope | None = None
    workflow_readiness_score: float | None = None
    workflow_readiness_grade: str | None = None
    workflow_pillar_scores: list[WorkflowPillarScore] = Field(default_factory=list)
    top_trust_gaps: list[str] = Field(default_factory=list)
    prioritized_remediation_actions: list[str] = Field(default_factory=list)
    operational_learning_suitability: OperationalLearningSuitabilitySummary | None = None
    claims_suitability: ClaimsSuitabilitySummary | None = None
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
