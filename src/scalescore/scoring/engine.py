from dataclasses import dataclass, field
from datetime import UTC, datetime

from scalescore.models.scaling import (
    CapacityConstraint,
    ConstraintType,
    FunctionalArea,
    GrowthSignal,
    ReadinessScore,
    RiskIndicator,
    RiskLevel,
)


@dataclass(frozen=True)
class ScoringConfig:
    """
    Scoring engine configuration.

    This can be initialized from the global settings or customized for testing.

    Usage:
        # Use global settings
        config = ScoringConfig.from_settings()

        # Or use defaults
        config = ScoringConfig()

        # Or customize
        config = ScoringConfig(base_score=80.0)
    """

    base_score: float = 100.0
    assessment_version: str = "1.0"
    growth_multiplier_cap: float = 2.0
    trend_delta_threshold: float = 1.0
    constraint_severity: dict[ConstraintType, float] = field(
        default_factory=lambda: {
            ConstraintType.CAPACITY: 15.0,
            ConstraintType.DEPENDENCY: 12.0,
            ConstraintType.GOVERNANCE: 8.0,
            ConstraintType.FINANCIAL: 20.0,
            ConstraintType.TALENT: 10.0,
            ConstraintType.TIMELINE: 5.0,
        }
    )
    risk_multipliers: dict[RiskLevel, float] = field(
        default_factory=lambda: {
            RiskLevel.LOW: 0.5,
            RiskLevel.MEDIUM: 1.0,
            RiskLevel.HIGH: 1.5,
            RiskLevel.CRITICAL: 2.5,
        }
    )

    @classmethod
    def from_settings(cls) -> "ScoringConfig":
        """
        Create ScoringConfig from global application settings.

        This bridges the centralized settings with the scoring engine.
        """
        from scalescore.config import settings

        scoring = settings.scoring
        return cls(
            base_score=scoring.base_score,
            assessment_version=scoring.assessment_version,
            growth_multiplier_cap=scoring.growth_multiplier_cap,
            trend_delta_threshold=scoring.trend_delta_threshold,
            constraint_severity={
                ConstraintType.CAPACITY: scoring.capacity_severity,
                ConstraintType.DEPENDENCY: scoring.dependency_severity,
                ConstraintType.GOVERNANCE: scoring.governance_severity,
                ConstraintType.FINANCIAL: scoring.financial_severity,
                ConstraintType.TALENT: scoring.talent_severity,
                ConstraintType.TIMELINE: scoring.timeline_severity,
            },
            risk_multipliers={
                RiskLevel.LOW: scoring.risk_low_multiplier,
                RiskLevel.MEDIUM: scoring.risk_medium_multiplier,
                RiskLevel.HIGH: scoring.risk_high_multiplier,
                RiskLevel.CRITICAL: scoring.risk_critical_multiplier,
            },
        )


class ScoringEngine:
    def __init__(self, config: ScoringConfig | None = None) -> None:
        self._config = config or ScoringConfig()

    def calculate_area_score(
        self,
        org_id: str,
        area: FunctionalArea,
        constraints: list[CapacityConstraint],
        risks: list[RiskIndicator],
        growth_signals: list[GrowthSignal],
        *,
        now: datetime | None = None,
        score_7d_ago: float | None = None,
        score_30d_ago: float | None = None,
    ) -> ReadinessScore:
        constraint_penalty = sum(
            self._constraint_severity(constraint)
            * constraint.breach_probability
            * self._time_proximity(constraint, now=now)
            for constraint in constraints
        )

        risk_penalty = sum(
            risk.impact_score * risk.probability * self._risk_severity_multiplier(risk.risk_level)
            for risk in risks
        )

        growth_multiplier = self._growth_intensity(growth_signals, area)
        base_score = self._config.base_score
        final_score = max(0.0, base_score - (constraint_penalty + risk_penalty) * growth_multiplier)
        score = round(final_score, 1)

        readiness = ReadinessScore(
            org_id=org_id,
            functional_area=area,
            score=score,
            sub_scores={
                "constraint_penalty": round(constraint_penalty, 3),
                "risk_penalty": round(risk_penalty, 3),
                "growth_multiplier": round(growth_multiplier, 3),
            },
            constraints=[constraint.id for constraint in constraints],
            risks=[risk.id for risk in risks],
            constraint_count=len(constraints),
            risk_count=len(risks),
            critical_risk_count=sum(1 for risk in risks if risk.risk_level == RiskLevel.CRITICAL),
            trend=self._calculate_trend(score, score_30d_ago),
            score_7d_ago=score_7d_ago,
            score_30d_ago=score_30d_ago,
            assessed_at=self._now(now),
            assessment_version=self._config.assessment_version,
        )

        readiness.grade = readiness.calculate_grade()
        return readiness

    def _constraint_severity(self, constraint: CapacityConstraint) -> float:
        return self._config.constraint_severity.get(constraint.constraint_type, 10.0)

    def _time_proximity(
        self, constraint: CapacityConstraint, *, now: datetime | None = None
    ) -> float:
        if not constraint.projected_breach_date:
            return 1.0

        current_time = self._now(now)
        days_until = (constraint.projected_breach_date - current_time).days

        if days_until < 30:
            return 2.0
        if days_until < 90:
            return 1.5
        if days_until < 180:
            return 1.0
        if days_until < 365:
            return 0.75
        return 0.5

    def _risk_severity_multiplier(self, level: RiskLevel) -> float:
        return self._config.risk_multipliers.get(level, 1.0)

    def _growth_intensity(self, signals: list[GrowthSignal], area: FunctionalArea) -> float:
        relevant = [signal for signal in signals if area in signal.affected_areas]
        if not relevant:
            return 1.0

        avg_magnitude = sum(signal.magnitude for signal in relevant) / len(relevant)
        multiplier = 1.0 + (avg_magnitude / 200.0)
        return min(self._config.growth_multiplier_cap, multiplier)

    def _calculate_trend(self, score: float, score_30d_ago: float | None) -> str:
        if score_30d_ago is None:
            return "stable"

        delta = score - score_30d_ago
        if delta >= self._config.trend_delta_threshold:
            return "improving"
        if delta <= -self._config.trend_delta_threshold:
            return "declining"
        return "stable"

    @staticmethod
    def _now(now: datetime | None) -> datetime:
        return now or datetime.now(UTC)
