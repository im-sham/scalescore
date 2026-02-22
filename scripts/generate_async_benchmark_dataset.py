#!/usr/bin/env python3
"""Generate schema-valid CSV datasets for async assessment load/stress validation."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random

REQUIRED_DATASET_FILES = (
    "organizations.csv",
    "teams.csv",
    "systems.csv",
    "vendors.csv",
    "facilities.csv",
    "growth_signals.csv",
)

FUNCTIONAL_AREAS = (
    "engineering",
    "operations",
    "finance",
    "product",
    "sales",
    "customer_success",
    "people",
    "marketing",
)

TEAM_FUNCTIONS = (
    "engineering",
    "operations",
    "finance",
    "people",
    "sales",
    "marketing",
    "support",
    "product",
)

SYSTEM_TYPES = (
    "service",
    "database",
    "queue",
    "analytics",
    "api_gateway",
)

VENDOR_TYPES = (
    "cloud",
    "saas",
    "security",
    "payments",
    "data",
)

SIGNAL_TYPES = (
    "headcount_plan",
    "revenue_target",
    "product_launch",
    "market_expansion",
)


def _parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def _build_output_dir(explicit_output_dir: str | None) -> Path:
    if explicit_output_dir:
        return Path(explicit_output_dir)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(".local/performance/datasets") / f"async-benchmark-{timestamp}"


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        writer.writerows(rows)


def generate_dataset(
    *,
    output_dir: Path,
    organizations: int,
    teams_per_org: int,
    systems_per_org: int,
    vendors_per_org: int,
    facilities_per_org: int,
    growth_signals_per_org: int,
    seed: int,
) -> dict[str, int]:
    random = Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    organization_rows: list[tuple[object, ...]] = []
    team_rows: list[tuple[object, ...]] = []
    system_rows: list[tuple[object, ...]] = []
    vendor_rows: list[tuple[object, ...]] = []
    facility_rows: list[tuple[object, ...]] = []
    growth_signal_rows: list[tuple[object, ...]] = []

    base_date = datetime.now(UTC).date()

    for org_idx in range(organizations):
        org_id = f"org-{org_idx + 1:04d}"
        org_name = f"Benchmark Org {org_idx + 1:04d}"
        projected_headcount = teams_per_org * (6 + (org_idx % 4))
        revenue_current = 25_000_000 + (org_idx * 350_000)
        burn_rate_monthly = 900_000 + (org_idx * 10_000)
        runway_months = round(revenue_current / max(burn_rate_monthly, 1), 1)
        organization_rows.append(
            (
                org_id,
                org_name,
                projected_headcount,
                f"{revenue_current:.2f}",
                f"{burn_rate_monthly:.2f}",
                f"{runway_months:.1f}",
            )
        )

        for team_idx in range(teams_per_org):
            team_id = f"team-{org_idx + 1:04d}-{team_idx + 1:05d}"
            team_name = f"{org_name} Team {team_idx + 1:05d}"
            team_function = TEAM_FUNCTIONS[team_idx % len(TEAM_FUNCTIONS)]
            headcount_current = 4 + (team_idx % 15)
            parent_team_id = (
                f"team-{org_idx + 1:04d}-{team_idx:05d}"
                if team_idx > 0 and team_idx % 9 == 0
                else ""
            )
            manager_id = f"mgr-{org_idx + 1:04d}-{(team_idx % 60) + 1:03d}"
            team_rows.append(
                (
                    team_id,
                    org_id,
                    team_name,
                    team_function,
                    headcount_current,
                    parent_team_id,
                    manager_id,
                )
            )

        for system_idx in range(systems_per_org):
            system_id = f"sys-{org_idx + 1:04d}-{system_idx + 1:05d}"
            system_name = f"{org_name} System {system_idx + 1:05d}"
            system_type = SYSTEM_TYPES[system_idx % len(SYSTEM_TYPES)]
            capacity_current = 1200 + (system_idx * 11)
            capacity_max = capacity_current + 350 + (system_idx % 120)
            is_critical = "true" if system_idx % 6 == 0 else "false"

            dependencies: list[str] = []
            if system_idx > 0:
                dependencies.append(f"sys-{org_idx + 1:04d}-{system_idx:05d}")
            if system_idx > 1 and system_idx % 4 == 0:
                dependencies.append(f"sys-{org_idx + 1:04d}-{system_idx - 1:05d}")

            system_rows.append(
                (
                    system_id,
                    org_id,
                    system_name,
                    system_type,
                    f"{capacity_current:.2f}",
                    f"{capacity_max:.2f}",
                    "requests_per_minute",
                    is_critical,
                    "|".join(dependencies),
                )
            )

        for vendor_idx in range(vendors_per_org):
            vendor_id = f"vendor-{org_idx + 1:04d}-{vendor_idx + 1:05d}"
            vendor_name = f"{org_name} Vendor {vendor_idx + 1:05d}"
            vendor_type = VENDOR_TYPES[vendor_idx % len(VENDOR_TYPES)]
            annual_cost = 18_000 + (vendor_idx * 170)
            is_critical = "true" if vendor_idx % 5 == 0 else "false"

            alternatives: list[str] = []
            if vendor_idx > 0 and vendor_idx % 3 == 0:
                alternatives.append(f"vendor-{org_idx + 1:04d}-{vendor_idx:05d}")
            if vendor_idx > 1 and vendor_idx % 8 == 0:
                alternatives.append(f"vendor-{org_idx + 1:04d}-{vendor_idx - 1:05d}")

            vendor_rows.append(
                (
                    vendor_id,
                    org_id,
                    vendor_name,
                    vendor_type,
                    f"{annual_cost:.2f}",
                    is_critical,
                    "|".join(alternatives),
                )
            )

        for facility_idx in range(facilities_per_org):
            facility_id = f"facility-{org_idx + 1:04d}-{facility_idx + 1:05d}"
            facility_name = f"{org_name} Facility {facility_idx + 1:05d}"
            capacity_seats = 120 + (facility_idx % 260)
            occupancy_ratio = 0.62 + (random.random() * 0.26)
            capacity_used = min(capacity_seats, int(capacity_seats * occupancy_ratio))
            lease_end_date = (base_date + timedelta(days=500 + (facility_idx % 730))).isoformat()
            location = f"Region-{(facility_idx % 12) + 1:02d}"

            facility_rows.append(
                (
                    facility_id,
                    org_id,
                    facility_name,
                    "office",
                    location,
                    capacity_seats,
                    capacity_used,
                    lease_end_date,
                )
            )

        for signal_idx in range(growth_signals_per_org):
            signal_id = f"signal-{org_idx + 1:04d}-{signal_idx + 1:05d}"
            signal_type = SIGNAL_TYPES[signal_idx % len(SIGNAL_TYPES)]
            signal_title = f"{org_name} {signal_type.replace('_', ' ').title()} {signal_idx + 1}"
            target_date = (
                datetime.now(UTC) + timedelta(days=45 + (signal_idx * 7))
            ).replace(microsecond=0)
            magnitude = 10.0 + (signal_idx % 90)
            magnitude_type = "percentage" if signal_idx % 2 == 0 else "absolute"
            confidence = round(0.55 + ((signal_idx % 9) * 0.05), 2)
            area_one = FUNCTIONAL_AREAS[signal_idx % len(FUNCTIONAL_AREAS)]
            area_two = FUNCTIONAL_AREAS[(signal_idx + 3) % len(FUNCTIONAL_AREAS)]
            affected_areas = f"{area_one}|{area_two}"

            growth_signal_rows.append(
                (
                    signal_id,
                    org_id,
                    signal_type,
                    signal_title,
                    target_date.isoformat(),
                    f"{magnitude:.2f}",
                    magnitude_type,
                    confidence,
                    affected_areas,
                )
            )

    organizations_path = output_dir / "organizations.csv"
    teams_path = output_dir / "teams.csv"
    systems_path = output_dir / "systems.csv"
    vendors_path = output_dir / "vendors.csv"
    facilities_path = output_dir / "facilities.csv"
    growth_signals_path = output_dir / "growth_signals.csv"

    _write_csv(
        organizations_path,
        (
            "id",
            "name",
            "headcount_current",
            "revenue_current",
            "burn_rate_monthly",
            "runway_months",
        ),
        organization_rows,
    )
    _write_csv(
        teams_path,
        ("id", "org_id", "name", "function", "headcount_current", "parent_team_id", "manager_id"),
        team_rows,
    )
    _write_csv(
        systems_path,
        (
            "id",
            "org_id",
            "name",
            "system_type",
            "capacity_current",
            "capacity_max",
            "capacity_unit",
            "is_critical",
            "dependencies",
        ),
        system_rows,
    )
    _write_csv(
        vendors_path,
        ("id", "org_id", "name", "vendor_type", "annual_cost", "is_critical", "alternatives"),
        vendor_rows,
    )
    _write_csv(
        facilities_path,
        (
            "id",
            "org_id",
            "name",
            "facility_type",
            "location",
            "capacity_seats",
            "capacity_used",
            "lease_end_date",
        ),
        facility_rows,
    )
    _write_csv(
        growth_signals_path,
        (
            "id",
            "org_id",
            "signal_type",
            "title",
            "target_date",
            "magnitude",
            "magnitude_type",
            "confidence",
            "affected_areas",
        ),
        growth_signal_rows,
    )

    file_sizes_bytes = {
        organizations_path.name: organizations_path.stat().st_size,
        teams_path.name: teams_path.stat().st_size,
        systems_path.name: systems_path.stat().st_size,
        vendors_path.name: vendors_path.stat().st_size,
        facilities_path.name: facilities_path.stat().st_size,
        growth_signals_path.name: growth_signals_path.stat().st_size,
    }

    summary = {
        "organizations": len(organization_rows),
        "teams": len(team_rows),
        "systems": len(system_rows),
        "vendors": len(vendor_rows),
        "facilities": len(facility_rows),
        "growth_signals": len(growth_signal_rows),
        "total_entities": (
            len(organization_rows)
            + len(team_rows)
            + len(system_rows)
            + len(vendor_rows)
            + len(facility_rows)
        ),
        "total_records_including_growth_signals": (
            len(organization_rows)
            + len(team_rows)
            + len(system_rows)
            + len(vendor_rows)
            + len(facility_rows)
            + len(growth_signal_rows)
        ),
        "seed": seed,
        "file_sizes_bytes": file_sizes_bytes,
        "largest_file_bytes": max(file_sizes_bytes.values()),
    }

    (output_dir / "dataset_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _validate_dataset_dir(path: Path) -> None:
    missing = [name for name in REQUIRED_DATASET_FILES if not (path / name).exists()]
    if missing:
        raise RuntimeError(f"dataset missing required files: {', '.join(missing)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate large schema-valid datasets for async assessment benchmarks."
    )
    parser.add_argument("--output-dir", help="Directory where CSV files are written")
    parser.add_argument("--overwrite", action="store_true", help="Replace output directory if it exists")
    parser.add_argument("--organizations", type=_parse_positive_int, default=1)
    parser.add_argument("--teams-per-org", type=_parse_positive_int, default=300)
    parser.add_argument("--systems-per-org", type=_parse_positive_int, default=300)
    parser.add_argument("--vendors-per-org", type=_parse_positive_int, default=300)
    parser.add_argument("--facilities-per-org", type=_parse_positive_int, default=300)
    parser.add_argument("--growth-signals-per-org", type=_parse_positive_int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = _build_output_dir(args.output_dir)

    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise RuntimeError(
                f"output directory already exists and is not empty: {output_dir}. "
                "Use --overwrite to replace it."
            )
        shutil.rmtree(output_dir)

    summary = generate_dataset(
        output_dir=output_dir,
        organizations=args.organizations,
        teams_per_org=args.teams_per_org,
        systems_per_org=args.systems_per_org,
        vendors_per_org=args.vendors_per_org,
        facilities_per_org=args.facilities_per_org,
        growth_signals_per_org=args.growth_signals_per_org,
        seed=args.seed,
    )
    _validate_dataset_dir(output_dir)

    print(f"Dataset generated at: {output_dir}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
