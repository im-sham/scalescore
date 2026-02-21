"""
Bottleneck Detector for ScaleScore.

Identifies and prioritizes scaling bottlenecks using:
1. Direct capacity analysis
2. Dependency cascade effects
3. Concentration risk analysis
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from scalescore.models.core import Facility, System, Vendor
from scalescore.models.scaling import (
    CapacityConstraint,
    ConstraintType,
    FunctionalArea,
    GrowthSignal,
    RiskIndicator,
    RiskLevel,
)


@dataclass
class DependencyNode:
    """Node in the dependency graph."""

    entity_id: str
    entity_type: str
    entity_name: str
    is_critical: bool = False
    dependents: list[str] = field(default_factory=list)  # entities that depend on this
    dependencies: list[str] = field(default_factory=list)  # entities this depends on


@dataclass
class BottleneckDetectorConfig:
    """Configuration for bottleneck detection thresholds."""

    capacity_warning_threshold: float = 0.7  # 70% utilization triggers warning
    capacity_critical_threshold: float = 0.8  # 80% triggers constraint
    concentration_risk_threshold: int = 3  # N+ dependents = concentration risk
    cascade_depth_limit: int = 5  # Max depth for cascade analysis
    growth_projection_months: int = 12  # How far to project growth


class BottleneckDetector:
    """
    Identifies and prioritizes scaling bottlenecks.

    Uses a dependency graph to find:
    1. Direct capacity constraints
    2. Cascade effects (A depends on B, B is constrained)
    3. Concentration risks (too many things depend on one entity)
    """

    def __init__(self, config: BottleneckDetectorConfig | None = None) -> None:
        self._config = config or BottleneckDetectorConfig()
        self._dependency_graph: dict[str, DependencyNode] = {}

    def detect_bottlenecks(
        self,
        org_id: str,
        systems: list[System],
        facilities: list[Facility],
        vendors: list[Vendor],
        growth_signals: list[GrowthSignal],
        *,
        now: datetime | None = None,
    ) -> tuple[list[CapacityConstraint], list[RiskIndicator]]:
        """
        Analyze entities against growth signals to find bottlenecks.

        Returns:
            Tuple of (constraints, risks) detected from the analysis.
        """
        current_time = now or datetime.now(UTC)
        constraints: list[CapacityConstraint] = []
        risks: list[RiskIndicator] = []

        # Phase 1: Build dependency graph
        self._dependency_graph = self._build_dependency_graph(systems, vendors)

        # Phase 2: Direct capacity analysis
        system_constraints = self._analyze_system_capacity(
            org_id, systems, growth_signals, current_time
        )
        facility_constraints = self._analyze_facility_capacity(
            org_id, facilities, growth_signals, current_time
        )
        constraints.extend(system_constraints)
        constraints.extend(facility_constraints)

        # Phase 3: Dependency cascade analysis
        cascade_risks = self._analyze_cascades(org_id, constraints, current_time)
        risks.extend(cascade_risks)

        # Phase 4: Concentration risk analysis
        concentration_risks = self._analyze_concentration(org_id, current_time)
        risks.extend(concentration_risks)

        # Phase 5: Vendor dependency risks
        vendor_risks = self._analyze_vendor_risks(org_id, vendors, current_time)
        risks.extend(vendor_risks)

        return constraints, risks

    def _build_dependency_graph(
        self, systems: list[System], vendors: list[Vendor]
    ) -> dict[str, DependencyNode]:
        """Build a dependency graph from systems and vendors."""
        graph: dict[str, DependencyNode] = {}

        # Add all systems to graph
        for system in systems:
            node = DependencyNode(
                entity_id=system.id,
                entity_type="system",
                entity_name=system.name,
                is_critical=system.is_critical,
                dependencies=list(system.dependencies),
            )
            graph[system.id] = node

        # Add vendors to graph
        for vendor in vendors:
            node = DependencyNode(
                entity_id=vendor.id,
                entity_type="vendor",
                entity_name=vendor.name,
                is_critical=vendor.is_critical,
            )
            graph[vendor.id] = node

        # Link systems to their vendors
        for system in systems:
            if system.vendor_id and system.vendor_id in graph:
                graph[system.id].dependencies.append(system.vendor_id)

        # Build reverse dependencies (who depends on whom)
        for entity_id, node in graph.items():
            for dep_id in node.dependencies:
                if dep_id in graph:
                    graph[dep_id].dependents.append(entity_id)

        return graph

    def _analyze_system_capacity(
        self,
        org_id: str,
        systems: list[System],
        growth_signals: list[GrowthSignal],
        now: datetime,
    ) -> list[CapacityConstraint]:
        """Check if system capacity will be exceeded given growth signals."""
        constraints: list[CapacityConstraint] = []

        for system in systems:
            if system.capacity_current is None or system.capacity_max is None:
                continue
            if system.capacity_max <= 0:
                continue

            current_util = system.capacity_current / system.capacity_max

            # Project future utilization based on growth signals
            projected_growth = self._project_growth_rate(system, growth_signals)
            projected_util = min(1.5, current_util * (1 + projected_growth))  # Cap at 150%

            if (
                projected_util >= self._config.capacity_critical_threshold
                or current_util >= self._config.capacity_critical_threshold
            ):
                breach_prob = min(
                    1.0,
                    (max(current_util, projected_util) - 0.8) / 0.2,
                )
                breach_date = self._estimate_breach_date(
                    system.capacity_current,
                    system.capacity_max,
                    projected_growth,
                    now,
                )

                constraints.append(
                    CapacityConstraint(
                        id=f"cap_{system.id}",
                        org_id=org_id,
                        entity_id=system.id,
                        entity_type="system",
                        entity_name=system.name,
                        constraint_type=ConstraintType.CAPACITY,
                        title=f"{system.name} approaching capacity limit",
                        description=f"System is at {current_util:.0%} capacity with projected growth to {projected_util:.0%}",
                        current_utilization=current_util,
                        current_value=system.capacity_current,
                        max_value=system.capacity_max,
                        unit=system.capacity_unit,
                        projected_utilization=projected_util,
                        projected_breach_date=breach_date,
                        breach_probability=breach_prob,
                        mitigation_options=self._suggest_system_mitigations(system),
                        mitigation_effort=self._estimate_mitigation_effort(system),
                    )
                )

        return constraints

    def _analyze_facility_capacity(
        self,
        org_id: str,
        facilities: list[Facility],
        growth_signals: list[GrowthSignal],
        now: datetime,
    ) -> list[CapacityConstraint]:
        """Check if facility capacity will be exceeded given growth signals."""
        constraints: list[CapacityConstraint] = []

        # Get headcount growth signals
        headcount_growth = sum(
            signal.magnitude / 100
            for signal in growth_signals
            if signal.signal_type == "headcount_plan" and signal.magnitude_type == "percentage"
        )

        for facility in facilities:
            if facility.capacity_seats <= 0:
                continue

            current_util = facility.capacity_used / facility.capacity_seats
            projected_util = min(1.5, current_util * (1 + headcount_growth))  # Cap at 150%

            if (
                projected_util >= self._config.capacity_critical_threshold
                or current_util >= self._config.capacity_critical_threshold
            ):
                breach_prob = min(
                    1.0,
                    (max(current_util, projected_util) - 0.8) / 0.2,
                )
                breach_date = self._estimate_breach_date(
                    facility.capacity_used,
                    facility.capacity_seats,
                    headcount_growth,
                    now,
                )

                mitigation_options = ["Secure additional office space", "Enable remote work"]
                if facility.expansion_possible:
                    mitigation_options.insert(0, "Expand current facility")

                constraints.append(
                    CapacityConstraint(
                        id=f"cap_{facility.id}",
                        org_id=org_id,
                        entity_id=facility.id,
                        entity_type="facility",
                        entity_name=facility.name,
                        constraint_type=ConstraintType.CAPACITY,
                        title=f"{facility.name} approaching seat capacity",
                        description=f"Facility is at {current_util:.0%} capacity with projected growth to {projected_util:.0%}",
                        current_utilization=current_util,
                        current_value=float(facility.capacity_used),
                        max_value=float(facility.capacity_seats),
                        unit="seats",
                        projected_utilization=projected_util,
                        projected_breach_date=breach_date,
                        breach_probability=breach_prob,
                        mitigation_options=mitigation_options,
                        mitigation_effort="high" if not facility.expansion_possible else "medium",
                    )
                )

        return constraints

    def _analyze_cascades(
        self,
        org_id: str,
        constraints: list[CapacityConstraint],
        now: datetime,
    ) -> list[RiskIndicator]:
        """
        Analyze cascade effects: if A depends on B, and B is constrained,
        A is at risk even if A itself has no direct constraints.
        """
        risks: list[RiskIndicator] = []
        constrained_ids = {c.entity_id for c in constraints}

        for entity_id, node in self._dependency_graph.items():
            if entity_id in constrained_ids:
                continue  # Already has direct constraint

            # Check if any dependency is constrained
            constrained_deps = [dep_id for dep_id in node.dependencies if dep_id in constrained_ids]

            if constrained_deps:
                dep_names = [
                    self._dependency_graph[dep_id].entity_name
                    for dep_id in constrained_deps
                    if dep_id in self._dependency_graph
                ]

                risk_level = RiskLevel.HIGH if node.is_critical else RiskLevel.MEDIUM

                risks.append(
                    RiskIndicator(
                        id=f"cascade_{entity_id}",
                        org_id=org_id,
                        title=f"{node.entity_name} at risk due to dependency constraints",
                        description=f"Depends on constrained systems: {', '.join(dep_names)}",
                        risk_level=risk_level,
                        functional_area=FunctionalArea.OPERATIONS,
                        constraint_type=ConstraintType.DEPENDENCY,
                        category="cascade_risk",
                        affected_entities=[entity_id] + constrained_deps,
                        related_constraints=[f"cap_{dep_id}" for dep_id in constrained_deps],
                        probability=0.7,
                        impact_score=0.8 if node.is_critical else 0.5,
                        recommendations=[
                            f"Monitor {node.entity_name} closely",
                            f"Prioritize capacity expansion for {', '.join(dep_names)}",
                        ],
                        evidence=[
                            f"Direct dependency on {len(constrained_deps)} constrained system(s)"
                        ],
                    )
                )

        return risks

    def _analyze_concentration(self, org_id: str, now: datetime) -> list[RiskIndicator]:
        """
        Identify concentration risks: too many things depend on one entity.
        """
        risks: list[RiskIndicator] = []

        for entity_id, node in self._dependency_graph.items():
            if len(node.dependents) >= self._config.concentration_risk_threshold:
                dependent_names = [
                    self._dependency_graph[dep_id].entity_name
                    for dep_id in node.dependents
                    if dep_id in self._dependency_graph
                ]

                risk_level = (
                    RiskLevel.CRITICAL
                    if node.is_critical and len(node.dependents) >= 5
                    else RiskLevel.HIGH
                    if node.is_critical or len(node.dependents) >= 5
                    else RiskLevel.MEDIUM
                )

                risks.append(
                    RiskIndicator(
                        id=f"concentration_{entity_id}",
                        org_id=org_id,
                        title=f"Concentration risk: {len(node.dependents)} systems depend on {node.entity_name}",
                        description=f"Single point of failure affecting: {', '.join(dependent_names[:5])}{'...' if len(dependent_names) > 5 else ''}",
                        risk_level=risk_level,
                        functional_area=FunctionalArea.OPERATIONS,
                        constraint_type=ConstraintType.DEPENDENCY,
                        category="concentration_risk",
                        affected_entities=[entity_id] + node.dependents,
                        probability=0.3,  # Lower probability but high impact
                        impact_score=min(1.0, 0.3 + (len(node.dependents) * 0.1)),
                        recommendations=[
                            f"Add redundancy for {node.entity_name}",
                            "Implement failover mechanisms",
                            "Document disaster recovery procedures",
                        ],
                        evidence=[f"{len(node.dependents)} systems directly depend on this entity"],
                    )
                )

        return risks

    def _analyze_vendor_risks(
        self, org_id: str, vendors: list[Vendor], now: datetime
    ) -> list[RiskIndicator]:
        """Analyze vendor-specific risks like contract expiration and single-vendor dependencies."""
        risks: list[RiskIndicator] = []

        for vendor in vendors:
            # Contract expiration risk
            if vendor.contract_end_date:
                days_until = (vendor.contract_end_date - now).days

                if days_until <= 90 and vendor.is_critical:
                    risk_level = RiskLevel.CRITICAL if days_until <= 30 else RiskLevel.HIGH

                    risks.append(
                        RiskIndicator(
                            id=f"vendor_contract_{vendor.id}",
                            org_id=org_id,
                            title=f"Critical vendor contract expiring: {vendor.name}",
                            description=f"Contract expires in {days_until} days. Vendor is marked as critical.",
                            risk_level=risk_level,
                            functional_area=FunctionalArea.OPERATIONS,
                            constraint_type=ConstraintType.DEPENDENCY,
                            category="vendor_contract",
                            affected_entities=[vendor.id],
                            probability=0.9,
                            impact_score=0.8,
                            projected_impact_date=vendor.contract_end_date,
                            time_to_impact_days=days_until,
                            recommendations=[
                                f"Initiate contract renewal with {vendor.name}",
                                "Evaluate alternative vendors"
                                if vendor.alternatives
                                else "Identify alternative vendors",
                            ],
                            evidence=[
                                f"Contract ends on {vendor.contract_end_date.strftime('%Y-%m-%d')}"
                            ],
                        )
                    )

            # No alternatives for critical vendor
            if vendor.is_critical and not vendor.alternatives:
                risks.append(
                    RiskIndicator(
                        id=f"vendor_noalt_{vendor.id}",
                        org_id=org_id,
                        title=f"No alternatives identified for critical vendor: {vendor.name}",
                        description="Critical vendor dependency with no documented alternatives.",
                        risk_level=RiskLevel.MEDIUM,
                        functional_area=FunctionalArea.OPERATIONS,
                        constraint_type=ConstraintType.DEPENDENCY,
                        category="vendor_dependency",
                        affected_entities=[vendor.id],
                        probability=0.4,
                        impact_score=0.7,
                        recommendations=[
                            f"Evaluate alternative vendors for {vendor.name}",
                            "Document contingency plan for vendor failure",
                        ],
                        evidence=["No alternatives field populated for critical vendor"],
                    )
                )

        return risks

    def _project_growth_rate(self, system: System, growth_signals: list[GrowthSignal]) -> float:
        """Project growth rate for a system based on growth signals."""
        # Default to headcount growth as proxy for system load
        total_growth = 0.0

        for signal in growth_signals:
            if signal.magnitude_type == "percentage":
                # Weight by confidence
                total_growth += (signal.magnitude / 100) * signal.confidence

        return total_growth

    def _estimate_breach_date(
        self,
        current: float,
        max_cap: float,
        growth_rate: float,
        now: datetime,
    ) -> datetime | None:
        """Estimate when capacity will be breached."""
        if growth_rate <= 0:
            return None

        current_util = current / max_cap
        if current_util >= 1.0:
            return now  # Already breached

        # Calculate months until 100% utilization
        # (1 + growth_rate)^months * current_util = 1.0
        # months = log(1/current_util) / log(1 + growth_rate)
        import math

        try:
            if growth_rate > 0:
                months = math.log(1.0 / current_util) / math.log(1 + growth_rate)
                days = int(months * 30)
                if days > 0 and days < 365 * 3:  # Cap at 3 years
                    from datetime import timedelta

                    return now + timedelta(days=days)
        except (ValueError, ZeroDivisionError):
            pass

        return None

    def _suggest_system_mitigations(self, system: System) -> list[str]:
        """Suggest mitigations based on system type."""
        mitigations = ["Upgrade system capacity"]

        system_type = system.system_type.lower()
        if system_type in ("saas", "cloud"):
            mitigations.append("Scale up cloud resources")
            mitigations.append("Negotiate higher tier with vendor")
        elif system_type == "custom":
            mitigations.append("Optimize code/queries for performance")
            mitigations.append("Add horizontal scaling")
        elif system_type in ("erp", "crm", "hris"):
            mitigations.append("Archive historical data")
            mitigations.append("Evaluate replacement systems")

        return mitigations

    def _estimate_mitigation_effort(self, system: System) -> str:
        """Estimate effort level for system mitigation."""
        if system.is_critical:
            return "high"  # Critical systems need careful migration
        if system.system_type.lower() in ("saas", "cloud"):
            return "low"  # Usually just config/payment
        return "medium"
