"""
Core entity models for ScaleScore.

These models are designed for compatibility with OpsOrchestra's EntityResponse pattern,
enabling seamless integration when ScaleScore operates as an OpsOrchestra module.
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EntityType(str, Enum):
    """Entity type enumeration, aligned with OpsOrchestra entity types."""

    ORGANIZATION = "organization"
    TEAM = "team"
    SYSTEM = "system"
    VENDOR = "vendor"
    FACILITY = "facility"
    ROLE = "role"
    PROCESS = "process"


class BaseEntity(BaseModel):
    """
    Base entity compatible with OpsOrchestra EntityResponse.

    All ScaleScore entities inherit from this base to ensure
    consistent structure and easy mapping to/from OpsOrchestra.
    """

    id: str
    type: EntityType
    name: str
    properties: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # OpsOrchestra compatibility fields
    aliases: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    source_docs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=True)


class Organization(BaseEntity):
    """
    Top-level organization entity.

    Contains aggregate metrics and growth plans that drive
    capacity requirements across all functional areas.
    """

    type: EntityType = EntityType.ORGANIZATION

    # Current state
    headcount_current: int = 0
    revenue_current: float = 0.0
    burn_rate_monthly: float = 0.0
    runway_months: float | None = None

    # Growth plans (key = quarter/period, value = target)
    headcount_plan: dict[str, int] = Field(default_factory=dict)
    revenue_plan: dict[str, float] = Field(default_factory=dict)

    # Organization metadata
    industry: str = ""
    stage: str = ""  # seed, series_a, series_b, etc.
    founded_year: int | None = None


class Team(BaseEntity):
    """
    Team or department within an organization.

    Teams have their own headcount plans and can be nested
    (parent_team_id) for hierarchical org structures.
    """

    type: EntityType = EntityType.TEAM

    org_id: str
    parent_team_id: str | None = None

    # Headcount
    headcount_current: int = 0
    headcount_plan: dict[str, int] = Field(default_factory=dict)

    # Team metadata
    manager_id: str | None = None
    function: str = ""  # engineering, sales, ops, finance, etc.
    cost_center: str | None = None

    # Capacity indicators
    avg_time_to_hire_days: int | None = None
    open_positions: int = 0


class System(BaseEntity):
    """
    Software system, tool, or platform.

    Systems have capacity limits and dependencies that
    can create bottlenecks during scaling.
    """

    type: EntityType = EntityType.SYSTEM

    org_id: str
    vendor_id: str | None = None

    # System classification
    system_type: str = ""  # erp, crm, hris, custom, infrastructure, etc.
    deployment: str = ""  # saas, on_prem, hybrid

    # Capacity metrics
    capacity_current: float | None = None
    capacity_max: float | None = None
    capacity_unit: str = ""  # users, transactions/day, GB, records, etc.

    # Criticality and dependencies
    is_critical: bool = False
    dependencies: list[str] = Field(default_factory=list)  # system_ids
    dependents: list[str] = Field(default_factory=list)  # systems that depend on this

    # Contract/support
    contract_end_date: datetime | None = None
    support_tier: str = ""  # basic, premium, enterprise
    monthly_cost: float = 0.0


class Vendor(BaseEntity):
    """
    External vendor or supplier.

    Vendors can be single points of failure if they're critical
    and lack alternatives.
    """

    type: EntityType = EntityType.VENDOR

    org_id: str

    # Vendor classification
    vendor_type: str = ""  # saas, contractor, supplier, consultant, etc.
    category: str = ""  # technology, services, facilities, etc.

    # Relationship details
    contract_start_date: datetime | None = None
    contract_end_date: datetime | None = None
    annual_cost: float = 0.0
    payment_terms: str = ""

    # Risk assessment
    is_critical: bool = False
    alternatives: list[str] = Field(default_factory=list)
    switching_cost: str = ""  # low, medium, high
    relationship_health: str = ""  # good, neutral, at_risk

    # Contact
    primary_contact: str = ""
    account_manager: str = ""


class Facility(BaseEntity):
    """
    Physical facility or location.

    Facilities have seat capacity that must scale with headcount,
    and lease timelines that can create constraints.
    """

    type: EntityType = EntityType.FACILITY

    org_id: str

    # Facility classification
    facility_type: str = ""  # office, warehouse, datacenter, lab, etc.
    location: str = ""
    address: str = ""

    # Capacity
    capacity_seats: int = 0
    capacity_used: int = 0
    capacity_sqft: int | None = None

    # Lease details
    lease_start_date: datetime | None = None
    lease_end_date: datetime | None = None
    monthly_rent: float = 0.0

    # Flexibility
    expansion_possible: bool = False
    expansion_seats_available: int = 0
    remote_policy: str = ""  # fully_remote, hybrid, in_office

    # Teams housed here
    team_ids: list[str] = Field(default_factory=list)
