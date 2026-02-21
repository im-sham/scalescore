import pytest

from scalescore.models.scaling import (
    CapacityConstraint,
    ConstraintType,
    FunctionalArea,
    RiskIndicator,
    RiskLevel,
)
from scalescore.scoring.recommender import (
    RecommendationEngine,
    RecommendationType,
    RecommenderConfig,
)


@pytest.fixture
def engine() -> RecommendationEngine:
    return RecommendationEngine()


@pytest.fixture
def capacity_constraint() -> CapacityConstraint:
    return CapacityConstraint(
        id="cap_sys_1",
        org_id="org_1",
        entity_id="sys_1",
        entity_type="system",
        entity_name="Main CRM",
        constraint_type=ConstraintType.CAPACITY,
        current_utilization=0.9,
        current_value=900.0,
        max_value=1000.0,
        unit="users",
        breach_probability=0.8,
    )


@pytest.fixture
def facility_constraint() -> CapacityConstraint:
    return CapacityConstraint(
        id="cap_fac_1",
        org_id="org_1",
        entity_id="fac_1",
        entity_type="facility",
        entity_name="HQ Office",
        constraint_type=ConstraintType.CAPACITY,
        current_utilization=0.85,
        current_value=85.0,
        max_value=100.0,
        unit="seats",
        breach_probability=0.5,
    )


@pytest.fixture
def concentration_risk() -> RiskIndicator:
    return RiskIndicator(
        id="risk_conc_1",
        org_id="org_1",
        title="Concentration risk: 5 systems depend on Central Auth",
        description="Single point of failure",
        risk_level=RiskLevel.HIGH,
        functional_area=FunctionalArea.OPERATIONS,
        constraint_type=ConstraintType.DEPENDENCY,
        category="concentration_risk",
        affected_entities=["sys_central"],
        probability=0.3,
        impact_score=0.8,
    )


@pytest.fixture
def vendor_contract_risk() -> RiskIndicator:
    return RiskIndicator(
        id="risk_vendor_1",
        org_id="org_1",
        title="Critical vendor contract expiring: SpecialSoftware",
        description="Contract expires in 30 days",
        risk_level=RiskLevel.CRITICAL,
        functional_area=FunctionalArea.OPERATIONS,
        constraint_type=ConstraintType.DEPENDENCY,
        category="vendor_contract",
        affected_entities=["ven_special"],
        probability=0.9,
        impact_score=0.8,
    )


class TestRecommendationEngineConstraints:
    def test_generates_recommendations_for_system_constraint(
        self, engine: RecommendationEngine, capacity_constraint: CapacityConstraint
    ) -> None:
        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=[capacity_constraint],
            risks=[],
        )

        assert len(recommendations) >= 1
        assert any(
            r.recommendation_type == RecommendationType.EXPAND_CAPACITY.value
            for r in recommendations
        )
        assert all(r.addresses_constraints == ["cap_sys_1"] for r in recommendations)

    def test_generates_recommendations_for_facility_constraint(
        self, engine: RecommendationEngine, facility_constraint: CapacityConstraint
    ) -> None:
        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=[facility_constraint],
            risks=[],
        )

        assert len(recommendations) >= 1
        rec_types = {r.recommendation_type for r in recommendations}
        assert (
            RecommendationType.SECURE_SPACE.value in rec_types
            or RecommendationType.ENABLE_REMOTE.value in rec_types
        )

    def test_high_utilization_triggers_replacement_recommendation(
        self, engine: RecommendationEngine
    ) -> None:
        critical_constraint = CapacityConstraint(
            id="cap_sys_crit",
            org_id="org_1",
            entity_id="sys_crit",
            entity_type="system",
            entity_name="Legacy System",
            constraint_type=ConstraintType.CAPACITY,
            current_utilization=0.98,
            breach_probability=0.95,
        )

        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=[critical_constraint],
            risks=[],
        )

        rec_types = {r.recommendation_type for r in recommendations}
        assert RecommendationType.REPLACE_SYSTEM.value in rec_types


class TestRecommendationEngineRisks:
    def test_generates_recommendations_for_concentration_risk(
        self, engine: RecommendationEngine, concentration_risk: RiskIndicator
    ) -> None:
        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=[],
            risks=[concentration_risk],
        )

        assert len(recommendations) >= 1
        assert any(
            r.recommendation_type == RecommendationType.ADD_REDUNDANCY.value
            for r in recommendations
        )

    def test_generates_recommendations_for_vendor_contract_risk(
        self, engine: RecommendationEngine, vendor_contract_risk: RiskIndicator
    ) -> None:
        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=[],
            risks=[vendor_contract_risk],
        )

        assert len(recommendations) >= 1
        assert any(
            r.recommendation_type == RecommendationType.RENEGOTIATE_CONTRACT.value
            for r in recommendations
        )


class TestRecommendationEnginePrioritization:
    def test_recommendations_sorted_by_priority(
        self,
        engine: RecommendationEngine,
        capacity_constraint: CapacityConstraint,
        facility_constraint: CapacityConstraint,
    ) -> None:
        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=[capacity_constraint, facility_constraint],
            risks=[],
        )

        if len(recommendations) >= 2:
            for i in range(len(recommendations) - 1):
                assert recommendations[i].priority_score >= recommendations[i + 1].priority_score

    def test_high_breach_probability_increases_priority(self, engine: RecommendationEngine) -> None:
        low_prob_constraint = CapacityConstraint(
            id="cap_low",
            org_id="org_1",
            entity_id="sys_low",
            entity_type="system",
            entity_name="Low Risk System",
            constraint_type=ConstraintType.CAPACITY,
            current_utilization=0.82,
            breach_probability=0.2,
        )
        high_prob_constraint = CapacityConstraint(
            id="cap_high",
            org_id="org_1",
            entity_id="sys_high",
            entity_type="system",
            entity_name="High Risk System",
            constraint_type=ConstraintType.CAPACITY,
            current_utilization=0.95,
            breach_probability=0.9,
        )

        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=[low_prob_constraint, high_prob_constraint],
            risks=[],
        )

        high_priority_recs = [r for r in recommendations if r.target_entity_id == "sys_high"]
        low_priority_recs = [r for r in recommendations if r.target_entity_id == "sys_low"]

        if high_priority_recs and low_priority_recs:
            assert high_priority_recs[0].priority_score > low_priority_recs[0].priority_score


class TestRecommendationEngineConfig:
    def test_respects_max_recommendations(self) -> None:
        config = RecommenderConfig(max_total_recommendations=3)
        engine = RecommendationEngine(config=config)

        constraints = [
            CapacityConstraint(
                id=f"cap_{i}",
                org_id="org_1",
                entity_id=f"sys_{i}",
                entity_type="system",
                entity_name=f"System {i}",
                constraint_type=ConstraintType.CAPACITY,
                current_utilization=0.9,
                breach_probability=0.5,
            )
            for i in range(10)
        ]

        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=constraints,
            risks=[],
        )

        assert len(recommendations) <= 3

    def test_deduplicates_recommendations(self, engine: RecommendationEngine) -> None:
        constraint = CapacityConstraint(
            id="cap_dup",
            org_id="org_1",
            entity_id="sys_dup",
            entity_type="system",
            entity_name="Duplicate Target System",
            constraint_type=ConstraintType.CAPACITY,
            current_utilization=0.9,
            breach_probability=0.5,
        )

        recommendations = engine.generate_recommendations(
            org_id="org_1",
            constraints=[constraint, constraint],
            risks=[],
        )

        seen_keys = set()
        for rec in recommendations:
            key = (rec.recommendation_type, rec.target_entity_id)
            assert key not in seen_keys
            seen_keys.add(key)
