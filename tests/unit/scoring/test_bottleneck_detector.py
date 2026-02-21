from datetime import UTC, datetime, timedelta

import pytest

from scalescore.models.core import Facility, System, Vendor
from scalescore.models.scaling import FunctionalArea, GrowthSignal
from scalescore.scoring.bottleneck_detector import BottleneckDetector, BottleneckDetectorConfig


@pytest.fixture
def detector() -> BottleneckDetector:
    return BottleneckDetector()


@pytest.fixture
def sample_systems() -> list[System]:
    return [
        System(
            id="sys_crm",
            org_id="org_1",
            name="Salesforce CRM",
            system_type="crm",
            capacity_current=850.0,
            capacity_max=1000.0,
            capacity_unit="users",
            is_critical=True,
            dependencies=[],
        ),
        System(
            id="sys_db",
            org_id="org_1",
            name="Main Database",
            system_type="database",
            capacity_current=70.0,
            capacity_max=100.0,
            capacity_unit="percent",
            is_critical=True,
            dependencies=[],
        ),
        System(
            id="sys_api",
            org_id="org_1",
            name="API Gateway",
            system_type="infrastructure",
            capacity_current=50.0,
            capacity_max=100.0,
            capacity_unit="percent",
            is_critical=False,
            dependencies=["sys_db"],
        ),
    ]


@pytest.fixture
def sample_facilities() -> list[Facility]:
    return [
        Facility(
            id="fac_hq",
            org_id="org_1",
            name="HQ Office",
            facility_type="office",
            location="San Francisco",
            capacity_seats=100,
            capacity_used=85,
            expansion_possible=False,
        ),
    ]


@pytest.fixture
def sample_vendors() -> list[Vendor]:
    return [
        Vendor(
            id="ven_aws",
            org_id="org_1",
            name="AWS",
            vendor_type="cloud",
            annual_cost=500000.0,
            is_critical=True,
            alternatives=["GCP", "Azure"],
        ),
        Vendor(
            id="ven_special",
            org_id="org_1",
            name="SpecialSoftware",
            vendor_type="saas",
            annual_cost=100000.0,
            is_critical=True,
            alternatives=[],
            contract_end_date=datetime.now(UTC) + timedelta(days=30),
        ),
    ]


@pytest.fixture
def sample_growth_signals() -> list[GrowthSignal]:
    return [
        GrowthSignal(
            id="sig_hc",
            org_id="org_1",
            signal_type="headcount_plan",
            title="Double headcount",
            target_date=datetime.now(UTC) + timedelta(days=365),
            magnitude=100.0,
            magnitude_type="percentage",
            confidence=0.8,
            affected_areas=[FunctionalArea.ENGINEERING, FunctionalArea.OPERATIONS],
        ),
    ]


class TestBottleneckDetectorCapacity:
    def test_detects_high_capacity_system(
        self,
        detector: BottleneckDetector,
        sample_systems: list[System],
        sample_growth_signals: list[GrowthSignal],
    ) -> None:
        constraints, _ = detector.detect_bottlenecks(
            org_id="org_1",
            systems=sample_systems,
            facilities=[],
            vendors=[],
            growth_signals=sample_growth_signals,
        )

        crm_constraint = next((c for c in constraints if c.entity_id == "sys_crm"), None)
        assert crm_constraint is not None
        assert crm_constraint.current_utilization == 0.85
        assert crm_constraint.breach_probability > 0

    def test_detects_high_capacity_facility(
        self,
        detector: BottleneckDetector,
        sample_facilities: list[Facility],
        sample_growth_signals: list[GrowthSignal],
    ) -> None:
        constraints, _ = detector.detect_bottlenecks(
            org_id="org_1",
            systems=[],
            facilities=sample_facilities,
            vendors=[],
            growth_signals=sample_growth_signals,
        )

        hq_constraint = next((c for c in constraints if c.entity_id == "fac_hq"), None)
        assert hq_constraint is not None
        assert hq_constraint.current_utilization == 0.85
        assert "seats" in hq_constraint.unit

    def test_skips_low_utilization_systems(
        self, detector: BottleneckDetector, sample_growth_signals: list[GrowthSignal]
    ) -> None:
        low_util_system = System(
            id="sys_low",
            org_id="org_1",
            name="Low Usage System",
            system_type="monitoring",
            capacity_current=20.0,
            capacity_max=100.0,
            capacity_unit="percent",
            is_critical=False,
        )

        constraints, _ = detector.detect_bottlenecks(
            org_id="org_1",
            systems=[low_util_system],
            facilities=[],
            vendors=[],
            growth_signals=[],
        )

        assert len(constraints) == 0


class TestBottleneckDetectorCascade:
    def test_detects_cascade_risk(
        self,
        detector: BottleneckDetector,
        sample_systems: list[System],
        sample_growth_signals: list[GrowthSignal],
    ) -> None:
        high_util_db = System(
            id="sys_db",
            org_id="org_1",
            name="Main Database",
            system_type="database",
            capacity_current=95.0,
            capacity_max=100.0,
            capacity_unit="percent",
            is_critical=True,
            dependencies=[],
        )
        api_depends_on_db = System(
            id="sys_api",
            org_id="org_1",
            name="API Gateway",
            system_type="infrastructure",
            capacity_current=30.0,
            capacity_max=100.0,
            capacity_unit="percent",
            is_critical=True,
            dependencies=["sys_db"],
        )

        _, risks = detector.detect_bottlenecks(
            org_id="org_1",
            systems=[high_util_db, api_depends_on_db],
            facilities=[],
            vendors=[],
            growth_signals=sample_growth_signals,
        )

        cascade_risks = [r for r in risks if r.category == "cascade_risk"]
        assert len(cascade_risks) >= 1
        assert any(r.affected_entities and "sys_api" in r.affected_entities for r in cascade_risks)


class TestBottleneckDetectorConcentration:
    def test_detects_concentration_risk(self, detector: BottleneckDetector) -> None:
        central_system = System(
            id="sys_central",
            org_id="org_1",
            name="Central Auth",
            system_type="auth",
            capacity_current=50.0,
            capacity_max=100.0,
            capacity_unit="percent",
            is_critical=True,
            dependencies=[],
        )
        dependent_systems = [
            System(
                id=f"sys_dep_{i}",
                org_id="org_1",
                name=f"Dependent System {i}",
                system_type="app",
                capacity_current=30.0,
                capacity_max=100.0,
                capacity_unit="percent",
                is_critical=False,
                dependencies=["sys_central"],
            )
            for i in range(5)
        ]

        _, risks = detector.detect_bottlenecks(
            org_id="org_1",
            systems=[central_system] + dependent_systems,
            facilities=[],
            vendors=[],
            growth_signals=[],
        )

        concentration_risks = [r for r in risks if r.category == "concentration_risk"]
        assert len(concentration_risks) >= 1
        assert any("sys_central" in r.affected_entities for r in concentration_risks)


class TestBottleneckDetectorVendor:
    def test_detects_expiring_contract(
        self, detector: BottleneckDetector, sample_vendors: list[Vendor]
    ) -> None:
        _, risks = detector.detect_bottlenecks(
            org_id="org_1",
            systems=[],
            facilities=[],
            vendors=sample_vendors,
            growth_signals=[],
        )

        contract_risks = [r for r in risks if r.category == "vendor_contract"]
        assert len(contract_risks) >= 1
        assert any("SpecialSoftware" in r.title for r in contract_risks)

    def test_detects_no_alternatives_risk(
        self, detector: BottleneckDetector, sample_vendors: list[Vendor]
    ) -> None:
        _, risks = detector.detect_bottlenecks(
            org_id="org_1",
            systems=[],
            facilities=[],
            vendors=sample_vendors,
            growth_signals=[],
        )

        no_alt_risks = [r for r in risks if r.category == "vendor_dependency"]
        assert len(no_alt_risks) >= 1
        assert any("SpecialSoftware" in r.title for r in no_alt_risks)


class TestBottleneckDetectorConfig:
    def test_custom_thresholds(self) -> None:
        config = BottleneckDetectorConfig(
            capacity_critical_threshold=0.9,
            concentration_risk_threshold=5,
        )
        detector = BottleneckDetector(config=config)

        system_at_85 = System(
            id="sys_test",
            org_id="org_1",
            name="Test System",
            system_type="app",
            capacity_current=85.0,
            capacity_max=100.0,
            capacity_unit="percent",
            is_critical=False,
        )

        constraints, _ = detector.detect_bottlenecks(
            org_id="org_1",
            systems=[system_at_85],
            facilities=[],
            vendors=[],
            growth_signals=[],
        )

        assert len(constraints) == 0
