from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from scalescore.core.exceptions import (
    CSVFormatError,
    ErrorCode,
    MissingRequiredFieldError,
    ValidationError,
)
from scalescore.models.core import Facility, Organization, System, Team, Vendor
from scalescore.models.scaling import FunctionalArea, GrowthSignal


@dataclass(frozen=True)
class CSVSchema:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


class CSVConnector:
    def __init__(self, *, strict_headers: bool = True) -> None:
        self._strict_headers = strict_headers

    def load_organizations(self, file_path: str | Path) -> list[Organization]:
        schema = CSVSchema(
            required=(
                "id",
                "name",
                "headcount_current",
                "revenue_current",
                "burn_rate_monthly",
                "runway_months",
            )
        )
        df = self._read_csv(file_path, schema)
        organizations: list[Organization] = []
        for _, row in df.iterrows():
            organizations.append(
                Organization(
                    id=self._required(row, "id"),
                    name=self._required(row, "name"),
                    headcount_current=self._to_required_int(row["headcount_current"], default=0),
                    revenue_current=self._to_required_float(row["revenue_current"], default=0.0),
                    burn_rate_monthly=self._to_required_float(
                        row["burn_rate_monthly"], default=0.0
                    ),
                    runway_months=self._to_float(row["runway_months"], default=None),
                )
            )
        return organizations

    def load_teams(self, file_path: str | Path) -> list[Team]:
        schema = CSVSchema(
            required=("id", "org_id", "name", "function", "headcount_current"),
            optional=("parent_team_id", "manager_id"),
        )
        df = self._read_csv(file_path, schema)
        teams: list[Team] = []
        for _, row in df.iterrows():
            teams.append(
                Team(
                    id=self._required(row, "id"),
                    org_id=self._required(row, "org_id"),
                    name=self._required(row, "name"),
                    function=self._required(row, "function"),
                    headcount_current=self._to_required_int(row["headcount_current"], default=0),
                    parent_team_id=self._to_str(row.get("parent_team_id")),
                    manager_id=self._to_str(row.get("manager_id")),
                )
            )
        return teams

    def load_systems(self, file_path: str | Path) -> list[System]:
        schema = CSVSchema(
            required=(
                "id",
                "org_id",
                "name",
                "system_type",
                "capacity_current",
                "capacity_max",
                "capacity_unit",
                "is_critical",
            ),
            optional=("dependencies",),
        )
        df = self._read_csv(file_path, schema)
        systems: list[System] = []
        for _, row in df.iterrows():
            systems.append(
                System(
                    id=self._required(row, "id"),
                    org_id=self._required(row, "org_id"),
                    name=self._required(row, "name"),
                    system_type=self._required(row, "system_type"),
                    capacity_current=self._to_float(row["capacity_current"], default=None),
                    capacity_max=self._to_float(row["capacity_max"], default=None),
                    capacity_unit=self._to_str(row.get("capacity_unit")) or "",
                    is_critical=self._to_bool(row["is_critical"]),
                    dependencies=self._to_list(row.get("dependencies")),
                )
            )
        return systems

    def load_vendors(self, file_path: str | Path) -> list[Vendor]:
        schema = CSVSchema(
            required=("id", "org_id", "name", "vendor_type", "annual_cost", "is_critical"),
            optional=("alternatives",),
        )
        df = self._read_csv(file_path, schema)
        vendors: list[Vendor] = []
        for _, row in df.iterrows():
            vendors.append(
                Vendor(
                    id=self._required(row, "id"),
                    org_id=self._required(row, "org_id"),
                    name=self._required(row, "name"),
                    vendor_type=self._required(row, "vendor_type"),
                    annual_cost=self._to_required_float(row["annual_cost"], default=0.0),
                    is_critical=self._to_bool(row["is_critical"]),
                    alternatives=self._to_list(row.get("alternatives")),
                )
            )
        return vendors

    def load_facilities(self, file_path: str | Path) -> list[Facility]:
        schema = CSVSchema(
            required=(
                "id",
                "org_id",
                "name",
                "facility_type",
                "location",
                "capacity_seats",
                "capacity_used",
                "lease_end_date",
            )
        )
        df = self._read_csv(file_path, schema)
        facilities: list[Facility] = []
        for _, row in df.iterrows():
            facilities.append(
                Facility(
                    id=self._required(row, "id"),
                    org_id=self._required(row, "org_id"),
                    name=self._required(row, "name"),
                    facility_type=self._required(row, "facility_type"),
                    location=self._required(row, "location"),
                    capacity_seats=self._to_required_int(row["capacity_seats"], default=0),
                    capacity_used=self._to_required_int(row["capacity_used"], default=0),
                    lease_end_date=self._to_date(row["lease_end_date"]),
                )
            )
        return facilities

    def load_growth_signals(self, file_path: str | Path) -> list[GrowthSignal]:
        schema = CSVSchema(
            required=(
                "id",
                "org_id",
                "signal_type",
                "title",
                "target_date",
                "magnitude",
                "magnitude_type",
                "confidence",
                "affected_areas",
            )
        )
        df = self._read_csv(file_path, schema)
        signals: list[GrowthSignal] = []
        for _, row in df.iterrows():
            signals.append(
                GrowthSignal(
                    id=self._required(row, "id"),
                    org_id=self._required(row, "org_id"),
                    signal_type=self._required(row, "signal_type"),
                    title=self._required(row, "title"),
                    target_date=self._to_datetime(row["target_date"]),
                    magnitude=self._to_required_float(row["magnitude"], default=0.0),
                    magnitude_type=self._required(row, "magnitude_type"),
                    confidence=self._to_float(row["confidence"], default=0.8) or 0.8,
                    affected_areas=self._to_functional_areas(row["affected_areas"]),
                )
            )
        return signals

    def load_all(self, directory: str | Path) -> dict[str, list]:
        base = Path(directory)
        expected = {
            "organizations": base / "organizations.csv",
            "teams": base / "teams.csv",
            "systems": base / "systems.csv",
            "vendors": base / "vendors.csv",
            "facilities": base / "facilities.csv",
            "growth_signals": base / "growth_signals.csv",
        }
        missing = [name for name, path in expected.items() if not path.exists()]
        if missing:
            raise CSVFormatError(
                message=f"Missing CSV files: {', '.join(missing)}",
                missing_columns=missing,
                file_path=str(base),
            )

        return {
            "organizations": self.load_organizations(expected["organizations"]),
            "teams": self.load_teams(expected["teams"]),
            "systems": self.load_systems(expected["systems"]),
            "vendors": self.load_vendors(expected["vendors"]),
            "facilities": self.load_facilities(expected["facilities"]),
            "growth_signals": self.load_growth_signals(expected["growth_signals"]),
        }

    def _read_csv(self, file_path: str | Path, schema: CSVSchema) -> pd.DataFrame:
        df = pd.read_csv(file_path)
        required = set(schema.required)
        optional = set(schema.optional)
        columns = list(df.columns)
        missing = [col for col in schema.required if col not in columns]
        if missing:
            raise CSVFormatError(
                message=f"Missing required columns: {', '.join(missing)}",
                missing_columns=missing,
                file_path=str(file_path),
            )
        if self._strict_headers:
            extras = [col for col in columns if col not in required | optional]
            if extras:
                raise CSVFormatError(
                    message=f"Unexpected columns: {', '.join(extras)}",
                    unexpected_columns=extras,
                    file_path=str(file_path),
                )
        return df

    @staticmethod
    def _is_missing(value: object) -> bool:
        if value is None:
            return True
        missing = pd.isna(value)
        if isinstance(missing, bool):
            return missing
        return False

    @staticmethod
    def _required(row: pd.Series, key: str) -> str:
        value = row.get(key)
        if CSVConnector._is_missing(value):
            raise MissingRequiredFieldError(field=key)
        text = str(value).strip()
        if text == "":
            raise MissingRequiredFieldError(field=key)
        return text

    @staticmethod
    def _to_str(value: object) -> str | None:
        if CSVConnector._is_missing(value):
            return None
        result = str(value).strip()
        return result if result else None

    @staticmethod
    def _to_int(value: object, *, default: int | None) -> int | None:
        if CSVConnector._is_missing(value):
            return default
        text = str(value).strip()
        if text == "":
            return default
        return int(float(text))

    @staticmethod
    def _to_required_int(value: object, *, default: int) -> int:
        parsed = CSVConnector._to_int(value, default=None)
        if parsed is None:
            return default
        return parsed

    @staticmethod
    def _to_float(value: object, *, default: float | None) -> float | None:
        if CSVConnector._is_missing(value):
            return default
        text = str(value).strip()
        if text == "":
            return default
        return float(text)

    @staticmethod
    def _to_required_float(value: object, *, default: float) -> float:
        parsed = CSVConnector._to_float(value, default=None)
        if parsed is None:
            return default
        return parsed

    @staticmethod
    def _to_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if CSVConnector._is_missing(value):
            return False
        normalized = str(value).strip().lower()
        return normalized in {"true", "1", "yes", "y"}

    @staticmethod
    def _to_list(value: object) -> list[str]:
        if CSVConnector._is_missing(value):
            return []
        text = str(value).strip()
        if not text:
            return []
        return [item.strip() for item in text.split("|") if item.strip()]

    @staticmethod
    def _to_date(value: object) -> datetime | None:
        if CSVConnector._is_missing(value):
            return None
        text = str(value).strip()
        if text == "":
            return None
        return datetime.strptime(text, "%Y-%m-%d")

    @staticmethod
    def _to_datetime(value: object) -> datetime:
        if CSVConnector._is_missing(value):
            raise ValidationError(
                message="Missing required datetime value",
                code=ErrorCode.INVALID_DATE_FORMAT,
            )
        text = str(value).strip()
        if text == "":
            raise ValidationError(
                message="Missing required datetime value",
                code=ErrorCode.INVALID_DATE_FORMAT,
            )
        return datetime.fromisoformat(text)

    @staticmethod
    def _to_functional_areas(value: object) -> list[FunctionalArea]:
        if CSVConnector._is_missing(value):
            return []
        text = str(value).strip()
        if text == "":
            return []
        raw = [item.strip() for item in text.split("|") if item.strip()]
        return [FunctionalArea(item) for item in raw]
