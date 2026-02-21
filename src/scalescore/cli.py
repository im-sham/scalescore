from __future__ import annotations

import argparse
import json
from pathlib import Path

from scalescore.core.assessment import run_assessment_from_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scalescore",
        description="Run an operational readiness assessment from CSV files.",
    )
    parser.add_argument(
        "--dataset-path",
        default="data",
        help="Directory containing organizations.csv, teams.csv, systems.csv, vendors.csv, facilities.csv, and growth_signals.csv.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON output (default prints a concise summary).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    report = run_assessment_from_csv(Path(args.dataset_path))

    if args.json:
        print(report.model_dump_json(indent=2))
        return

    summary = {
        "report_id": report.report_id,
        "org_id": report.org_id,
        "org_name": report.org_name,
        "overall_score": report.overall_score,
        "overall_grade": report.overall_grade,
        "total_constraints": report.total_constraints,
        "total_risks": report.total_risks,
        "total_recommendations": report.total_recommendations,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
