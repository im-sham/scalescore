from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scalescore.connectors.csv_connector import CSVConnector
from scalescore.core.exceptions import (
    MultipleOrganizationsError,
    OrganizationRequiredError,
)
from scalescore.core.reporting import generate_executive_summary
from scalescore.models.core import Facility, Organization, System, Team, Vendor
from scalescore.models.scaling import (
    CapacityConstraint,
    FunctionalArea,
    RiskIndicator,
    RiskLevel,
    ScaleScoreReport,
)
from scalescore.scoring.bottleneck_detector import BottleneckDetector
from scalescore.scoring.engine import ScoringConfig, ScoringEngine
from scalescore.scoring.recommender import RecommendationEngine


def run_assessment_from_csv(directory: str | Path) -> ScaleScoreReport:
    connector = CSVConnector()
    data = connector.load_all(directory)
    return run_assessment(
        organizations=data["organizations"],
        teams=data["teams"],
        systems=data["systems"],
        vendors=data["vendors"],
        facilities=data["facilities"],
        growth_signals=data["growth_signals"],
    )


def run_assessment(
    *,
    organizations: list[Organization],
    teams: list[Team] | None = None,
    systems: list[System],
    vendors: list[Vendor] | None = None,
    facilities: list[Facility],
    growth_signals: list,
) -> ScaleScoreReport:
    if not organizations:
        raise OrganizationRequiredError()

    org_ids = {org.id for org in organizations}
    if len(org_ids) > 1:
        raise MultipleOrganizationsError(count=len(org_ids))

    organization = organizations[0]
    teams = teams or []
    vendors = vendors or []

    detector = BottleneckDetector()
    constraints, risks = detector.detect_bottlenecks(
        org_id=organization.id,
        systems=systems,
        facilities=facilities,
        vendors=vendors,
        growth_signals=growth_signals,
    )

    constraint_by_area: dict[FunctionalArea, list[CapacityConstraint]] = {
        area: [] for area in FunctionalArea
    }
    for constraint in constraints:
        area = _constraint_area(constraint)
        constraint_by_area[area].append(constraint)

    risk_by_area: dict[FunctionalArea, list[RiskIndicator]] = {area: [] for area in FunctionalArea}
    for risk in risks:
        risk_by_area[risk.functional_area].append(risk)

    areas = _assessment_areas(constraint_by_area, risk_by_area, growth_signals)
    engine = ScoringEngine(config=ScoringConfig.from_settings())
    area_scores = [
        engine.calculate_area_score(
            org_id=organization.id,
            area=area,
            constraints=constraint_by_area.get(area, []),
            risks=risk_by_area.get(area, []),
            growth_signals=growth_signals,
        )
        for area in areas
    ]

    overall_score = (
        round(sum(score.score for score in area_scores) / len(area_scores), 1)
        if area_scores
        else 0.0
    )

    recommender = RecommendationEngine()
    recommendations = recommender.generate_recommendations(
        org_id=organization.id,
        constraints=constraints,
        risks=risks,
    )

    top_risks = sorted(risks, key=lambda r: r.risk_score, reverse=True)[:5]
    critical_risks = sum(1 for r in risks if r.risk_level == RiskLevel.CRITICAL)
    high_risks = sum(1 for r in risks if r.risk_level == RiskLevel.HIGH)

    report = ScaleScoreReport(
        report_id=str(uuid4()),
        org_id=organization.id,
        org_name=organization.name,
        generated_at=datetime.now(UTC),
        overall_score=overall_score,
        overall_grade=_grade_for_score(overall_score),
        overall_trend=_overall_trend(area_scores),
        area_scores=area_scores,
        top_risks=top_risks,
        constraints=constraints,
        recommendations=recommendations,
        growth_signals=growth_signals,
        total_risks=len(risks),
        critical_risks=critical_risks,
        high_risks=high_risks,
        total_constraints=len(constraints),
        total_recommendations=len(recommendations),
        executive_summary="",
        key_findings=_generate_key_findings(constraints, risks),
        immediate_actions=_generate_immediate_actions(recommendations),
    )
    report.executive_summary = generate_executive_summary(report)

    return report


def _assessment_areas(
    constraint_by_area: dict[FunctionalArea, list[CapacityConstraint]],
    risk_by_area: dict[FunctionalArea, list[RiskIndicator]],
    growth_signals: list,
) -> list[FunctionalArea]:
    areas = {area for area, constraints in constraint_by_area.items() if constraints}
    areas.update(area for area, risks in risk_by_area.items() if risks)
    for signal in growth_signals:
        areas.update(signal.affected_areas)
    if not areas:
        return list(FunctionalArea)
    return [area for area in FunctionalArea if area in areas]


def _constraint_area(constraint: CapacityConstraint) -> FunctionalArea:
    if constraint.entity_type == "facility":
        return FunctionalArea.FACILITIES
    return FunctionalArea.OPERATIONS


def _overall_trend(area_scores: list) -> str:
    if not area_scores:
        return "stable"

    trends = [score.trend for score in area_scores]
    improving = trends.count("improving")
    declining = trends.count("declining")

    if declining > improving:
        return "declining"
    if improving > declining:
        return "improving"
    return "stable"


def _grade_for_score(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _generate_key_findings(
    constraints: list[CapacityConstraint],
    risks: list[RiskIndicator],
) -> list[str]:
    findings: list[str] = []

    high_util_constraints = [c for c in constraints if c.current_utilization >= 0.9]
    if high_util_constraints:
        names = [c.entity_name for c in high_util_constraints[:3]]
        findings.append(
            f"{len(high_util_constraints)} system(s) at critical capacity: {', '.join(names)}"
        )

    critical_risks = [r for r in risks if r.risk_level == RiskLevel.CRITICAL]
    if critical_risks:
        findings.append(f"{len(critical_risks)} critical risk(s) require immediate attention")

    cascade_risks = [r for r in risks if r.category == "cascade_risk"]
    if cascade_risks:
        findings.append(f"{len(cascade_risks)} cascade risk(s) from dependency constraints")

    concentration_risks = [r for r in risks if r.category == "concentration_risk"]
    if concentration_risks:
        findings.append(f"{len(concentration_risks)} concentration risk(s) identified")

    return findings[:5]


def _generate_immediate_actions(recommendations: list) -> list[str]:
    high_priority = [r for r in recommendations if r.priority_score >= 1.5]
    return [r.title for r in high_priority[:3]]
