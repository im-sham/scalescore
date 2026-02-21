from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from scalescore.models.scaling import (
    CapacityConstraint,
    ConstraintType,
    Recommendation,
    RiskIndicator,
    RiskLevel,
)


class RecommendationType(StrEnum):
    EXPAND_CAPACITY = "expand_capacity"
    ADD_REDUNDANCY = "add_redundancy"
    ACCELERATE_HIRING = "accelerate_hiring"
    DEFER_GROWTH = "defer_growth"
    REPLACE_SYSTEM = "replace_system"
    RENEGOTIATE_CONTRACT = "renegotiate_contract"
    ADD_GOVERNANCE = "add_governance"
    CREATE_CONTINGENCY = "create_contingency"
    ENABLE_REMOTE = "enable_remote"
    SECURE_SPACE = "secure_space"


EFFORT_VALUES = {"low": 1, "medium": 2, "high": 3}
IMPACT_VALUES = {"low": 1, "medium": 2, "high": 3}


@dataclass
class RecommenderConfig:
    max_recommendations_per_constraint: int = 2
    max_recommendations_per_risk: int = 2
    max_total_recommendations: int = 15


class RecommendationEngine:
    def __init__(self, config: RecommenderConfig | None = None) -> None:
        self._config = config or RecommenderConfig()
        self._patterns = self._build_patterns()

    def generate_recommendations(
        self,
        org_id: str,
        constraints: list[CapacityConstraint],
        risks: list[RiskIndicator],
        *,
        now: datetime | None = None,
    ) -> list[Recommendation]:
        current_time = now or datetime.now(UTC)
        recommendations: list[Recommendation] = []

        for constraint in constraints:
            recs = self._recommendations_for_constraint(org_id, constraint, current_time)
            recommendations.extend(recs[: self._config.max_recommendations_per_constraint])

        for risk in risks:
            recs = self._recommendations_for_risk(org_id, risk, current_time)
            recommendations.extend(recs[: self._config.max_recommendations_per_risk])

        recommendations = self._dedupe_recommendations(recommendations)
        recommendations = self._prioritize(recommendations)

        return recommendations[: self._config.max_total_recommendations]

    def _recommendations_for_constraint(
        self,
        org_id: str,
        constraint: CapacityConstraint,
        now: datetime,
    ) -> list[Recommendation]:
        recommendations: list[Recommendation] = []

        for pattern in self._patterns:
            if pattern.matches_constraint(constraint):
                rec = self._create_recommendation(
                    org_id=org_id,
                    pattern=pattern,
                    constraint=constraint,
                    risk=None,
                    now=now,
                )
                recommendations.append(rec)

        return recommendations

    def _recommendations_for_risk(
        self,
        org_id: str,
        risk: RiskIndicator,
        now: datetime,
    ) -> list[Recommendation]:
        recommendations: list[Recommendation] = []

        for pattern in self._patterns:
            if pattern.matches_risk(risk):
                rec = self._create_recommendation(
                    org_id=org_id,
                    pattern=pattern,
                    constraint=None,
                    risk=risk,
                    now=now,
                )
                recommendations.append(rec)

        return recommendations

    def _create_recommendation(
        self,
        org_id: str,
        pattern: "RecommendationPattern",
        constraint: CapacityConstraint | None,
        risk: RiskIndicator | None,
        now: datetime,
    ) -> Recommendation:
        target_id = (
            constraint.entity_id
            if constraint
            else (risk.affected_entities[0] if risk and risk.affected_entities else "")
        )
        target_type = constraint.entity_type if constraint else "risk"
        target_name = constraint.entity_name if constraint else (risk.title if risk else "")

        title = pattern.title_template.format(
            entity_name=target_name,
            constraint_type=constraint.constraint_type.value if constraint else "",
            risk_level=risk.risk_level.value if risk else "",
        )

        description = pattern.description_template.format(
            entity_name=target_name,
            utilization=f"{constraint.current_utilization:.0%}" if constraint else "",
            risk_title=risk.title if risk else "",
        )

        priority_score = self._calculate_priority(pattern, constraint, risk)

        return Recommendation(
            id=f"rec_{uuid4().hex[:8]}",
            org_id=org_id,
            title=title,
            description=description,
            recommendation_type=pattern.rec_type.value,
            target_entity_id=target_id,
            target_entity_type=target_type,
            addresses_risks=[risk.id] if risk else [],
            addresses_constraints=[constraint.id] if constraint else [],
            effort=pattern.effort,
            impact=pattern.impact,
            priority_score=priority_score,
            estimated_time_days=pattern.estimated_days,
            status="proposed",
        )

    def _calculate_priority(
        self,
        pattern: "RecommendationPattern",
        constraint: CapacityConstraint | None,
        risk: RiskIndicator | None,
    ) -> float:
        impact_val = IMPACT_VALUES.get(pattern.impact, 2)
        effort_val = EFFORT_VALUES.get(pattern.effort, 2)
        base_priority = impact_val / effort_val

        urgency_multiplier = 1.0
        if constraint and constraint.breach_probability >= 0.8:
            urgency_multiplier = 1.5
        elif risk and risk.risk_level == RiskLevel.CRITICAL:
            urgency_multiplier = 1.5
        elif risk and risk.risk_level == RiskLevel.HIGH:
            urgency_multiplier = 1.25

        return round(base_priority * urgency_multiplier, 2)

    def _dedupe_recommendations(
        self, recommendations: list[Recommendation]
    ) -> list[Recommendation]:
        seen: set[tuple[str, str]] = set()
        deduped: list[Recommendation] = []

        for rec in recommendations:
            key = (rec.recommendation_type, rec.target_entity_id)
            if key not in seen:
                seen.add(key)
                deduped.append(rec)

        return deduped

    def _prioritize(self, recommendations: list[Recommendation]) -> list[Recommendation]:
        return sorted(recommendations, key=lambda r: r.priority_score, reverse=True)

    def _build_patterns(self) -> list["RecommendationPattern"]:
        return [
            RecommendationPattern(
                rec_type=RecommendationType.EXPAND_CAPACITY,
                constraint_types=[ConstraintType.CAPACITY],
                entity_types=["system"],
                title_template="Expand capacity for {entity_name}",
                description_template="System is at {utilization} capacity. Consider upgrading to handle projected load.",
                effort="medium",
                impact="high",
                estimated_days=30,
            ),
            RecommendationPattern(
                rec_type=RecommendationType.REPLACE_SYSTEM,
                constraint_types=[ConstraintType.CAPACITY],
                entity_types=["system"],
                min_utilization=0.95,
                title_template="Evaluate replacement for {entity_name}",
                description_template="System is at {utilization} capacity. Near-term limits may require migration to scalable alternative.",
                effort="high",
                impact="high",
                estimated_days=90,
            ),
            RecommendationPattern(
                rec_type=RecommendationType.SECURE_SPACE,
                constraint_types=[ConstraintType.CAPACITY],
                entity_types=["facility"],
                title_template="Secure additional space for {entity_name}",
                description_template="Facility is at {utilization} capacity. Explore expansion or additional locations.",
                effort="high",
                impact="high",
                estimated_days=60,
            ),
            RecommendationPattern(
                rec_type=RecommendationType.ENABLE_REMOTE,
                constraint_types=[ConstraintType.CAPACITY],
                entity_types=["facility"],
                title_template="Enable remote work to reduce {entity_name} load",
                description_template="Facility capacity can be preserved by enabling remote work policies.",
                effort="low",
                impact="medium",
                estimated_days=14,
            ),
            RecommendationPattern(
                rec_type=RecommendationType.ADD_REDUNDANCY,
                risk_categories=["concentration_risk", "cascade_risk"],
                title_template="Add redundancy for {entity_name}",
                description_template="High dependency concentration. Implement failover or backup systems.",
                effort="high",
                impact="high",
                estimated_days=60,
            ),
            RecommendationPattern(
                rec_type=RecommendationType.RENEGOTIATE_CONTRACT,
                risk_categories=["vendor_contract"],
                title_template="Renegotiate contract: {entity_name}",
                description_template="Critical vendor contract expiring soon. Initiate renewal negotiations.",
                effort="medium",
                impact="high",
                estimated_days=30,
            ),
            RecommendationPattern(
                rec_type=RecommendationType.CREATE_CONTINGENCY,
                risk_categories=["vendor_dependency"],
                title_template="Create contingency plan for {entity_name}",
                description_template="No alternatives identified. Document backup procedures and evaluate alternatives.",
                effort="low",
                impact="medium",
                estimated_days=14,
            ),
        ]


@dataclass
class RecommendationPattern:
    rec_type: RecommendationType
    title_template: str
    description_template: str
    effort: str
    impact: str
    estimated_days: int
    constraint_types: list[ConstraintType] = field(default_factory=list)
    entity_types: list[str] = field(default_factory=list)
    risk_categories: list[str] = field(default_factory=list)
    risk_levels: list[RiskLevel] = field(default_factory=list)
    min_utilization: float = 0.0

    def matches_constraint(self, constraint: CapacityConstraint) -> bool:
        if not self.constraint_types:
            return False

        if constraint.constraint_type not in self.constraint_types:
            return False

        if self.entity_types and constraint.entity_type not in self.entity_types:
            return False

        if self.min_utilization > 0 and constraint.current_utilization < self.min_utilization:
            return False

        return True

    def matches_risk(self, risk: RiskIndicator) -> bool:
        if not self.risk_categories and not self.risk_levels:
            return False

        if self.risk_categories and risk.category not in self.risk_categories:
            return False

        if self.risk_levels and risk.risk_level not in self.risk_levels:
            return False

        return True
