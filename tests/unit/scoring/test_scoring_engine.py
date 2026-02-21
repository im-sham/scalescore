from datetime import datetime, timedelta

from scalescore.models.scaling import (
    CapacityConstraint,
    ConstraintType,
    FunctionalArea,
    GrowthSignal,
    RiskIndicator,
    RiskLevel,
)
from scalescore.scoring.engine import ScoringEngine


def test_score_penalizes_constraints_and_risks() -> None:
    now = datetime(2026, 1, 1)
    engine = ScoringEngine()

    constraint = CapacityConstraint(
        id="cap_1",
        org_id="org_1",
        entity_id="sys_1",
        entity_type="system",
        constraint_type=ConstraintType.CAPACITY,
        current_utilization=0.9,
        breach_probability=0.5,
        projected_breach_date=now + timedelta(days=20),
    )
    risk = RiskIndicator(
        id="risk_1",
        org_id="org_1",
        title="Critical outage",
        description="Single point of failure",
        risk_level=RiskLevel.CRITICAL,
        functional_area=FunctionalArea.ENGINEERING,
        constraint_type=ConstraintType.DEPENDENCY,
        probability=0.4,
        impact_score=0.6,
    )

    result = engine.calculate_area_score(
        org_id="org_1",
        area=FunctionalArea.ENGINEERING,
        constraints=[constraint],
        risks=[risk],
        growth_signals=[],
        now=now,
    )

    assert result.score < 100
    assert result.constraint_count == 1
    assert result.risk_count == 1
    assert result.critical_risk_count == 1
    assert result.grade in {"A", "B", "C", "D", "F"}


def test_growth_signal_increases_penalty() -> None:
    now = datetime(2026, 1, 1)
    engine = ScoringEngine()

    constraint = CapacityConstraint(
        id="cap_2",
        org_id="org_1",
        entity_id="sys_2",
        entity_type="system",
        constraint_type=ConstraintType.CAPACITY,
        current_utilization=0.85,
        breach_probability=0.4,
        projected_breach_date=now + timedelta(days=90),
    )

    baseline = engine.calculate_area_score(
        org_id="org_1",
        area=FunctionalArea.ENGINEERING,
        constraints=[constraint],
        risks=[],
        growth_signals=[],
        now=now,
    ).score

    growth_signal = GrowthSignal(
        id="gs_1",
        org_id="org_1",
        signal_type="headcount_plan",
        title="Double headcount",
        target_date=now + timedelta(days=180),
        magnitude=100.0,
        magnitude_type="percentage",
        confidence=0.8,
        affected_areas=[FunctionalArea.ENGINEERING],
    )

    amplified = engine.calculate_area_score(
        org_id="org_1",
        area=FunctionalArea.ENGINEERING,
        constraints=[constraint],
        risks=[],
        growth_signals=[growth_signal],
        now=now,
    ).score

    assert amplified < baseline


def test_trend_calculates_from_history() -> None:
    engine = ScoringEngine()
    score = engine.calculate_area_score(
        org_id="org_1",
        area=FunctionalArea.FINANCE,
        constraints=[],
        risks=[],
        growth_signals=[],
        score_30d_ago=90.0,
    )

    assert score.trend == "improving"
