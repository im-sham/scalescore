#!/usr/bin/env python3
"""Evaluate async benchmark artifacts against staging release-gate criteria."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GateCheck:
    criterion: str
    required: bool
    passed: bool
    details: str


def _parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object at {path}")
    return payload


def _bool_label(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def evaluate_gate(
    *,
    benchmark_results: dict[str, Any],
    dataset_summary: dict[str, Any] | None,
    min_total_entities: int,
    baseline_p95_seconds: float | None,
    max_p95_regression_percent: float,
) -> dict[str, Any]:
    results = benchmark_results.get("results")
    if not isinstance(results, dict):
        raise RuntimeError("benchmark results payload missing 'results' object")

    submitted_jobs = int(results.get("submitted_jobs", 0))
    completed_jobs = int(results.get("completed_jobs", 0))
    failed_jobs = int(results.get("failed_jobs", 0))
    timed_out_jobs = int(results.get("timed_out_jobs", 0))

    completion_latency = results.get("completion_latency_seconds")
    if isinstance(completion_latency, dict):
        p95_value_raw = completion_latency.get("p95")
    else:
        p95_value_raw = None
    p95_seconds = float(p95_value_raw) if p95_value_raw is not None else None

    checks: list[GateCheck] = []
    checks.append(
        GateCheck(
            criterion="submitted_jobs > 0",
            required=True,
            passed=submitted_jobs > 0,
            details=f"submitted_jobs={submitted_jobs}",
        )
    )
    checks.append(
        GateCheck(
            criterion="completed_jobs == submitted_jobs",
            required=True,
            passed=(completed_jobs == submitted_jobs),
            details=f"completed_jobs={completed_jobs}, submitted_jobs={submitted_jobs}",
        )
    )
    checks.append(
        GateCheck(
            criterion="failed_jobs == 0",
            required=True,
            passed=(failed_jobs == 0),
            details=f"failed_jobs={failed_jobs}",
        )
    )
    checks.append(
        GateCheck(
            criterion="timed_out_jobs == 0",
            required=True,
            passed=(timed_out_jobs == 0),
            details=f"timed_out_jobs={timed_out_jobs}",
        )
    )
    checks.append(
        GateCheck(
            criterion="completion_latency_seconds.p95 captured",
            required=True,
            passed=(p95_seconds is not None),
            details=f"p95_seconds={p95_seconds}",
        )
    )

    if dataset_summary is None:
        checks.append(
            GateCheck(
                criterion=f"dataset total_entities >= {min_total_entities}",
                required=True,
                passed=False,
                details="dataset summary missing",
            )
        )
    else:
        total_entities = int(dataset_summary.get("total_entities", 0))
        checks.append(
            GateCheck(
                criterion=f"dataset total_entities >= {min_total_entities}",
                required=True,
                passed=(total_entities >= min_total_entities),
                details=f"total_entities={total_entities}",
            )
        )

    if baseline_p95_seconds is None:
        checks.append(
            GateCheck(
                criterion=(
                    "completion_latency_seconds.p95 <= baseline * "
                    f"(1 + {max_p95_regression_percent}% )"
                ),
                required=False,
                passed=True,
                details="baseline_p95_seconds not provided; regression check skipped",
            )
        )
    elif p95_seconds is None:
        checks.append(
            GateCheck(
                criterion=(
                    "completion_latency_seconds.p95 <= baseline * "
                    f"(1 + {max_p95_regression_percent}% )"
                ),
                required=True,
                passed=False,
                details="p95_seconds missing while baseline regression check is enabled",
            )
        )
    else:
        max_allowed = baseline_p95_seconds * (1.0 + (max_p95_regression_percent / 100.0))
        checks.append(
            GateCheck(
                criterion=(
                    "completion_latency_seconds.p95 <= baseline * "
                    f"(1 + {max_p95_regression_percent}% )"
                ),
                required=True,
                passed=(p95_seconds <= max_allowed),
                details=(
                    f"p95_seconds={round(p95_seconds, 4)}, "
                    f"baseline_p95_seconds={round(baseline_p95_seconds, 4)}, "
                    f"max_allowed={round(max_allowed, 4)}"
                ),
            )
        )

    required_checks = [check for check in checks if check.required]
    overall_pass = all(check.passed for check in required_checks)

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "overall_pass": overall_pass,
        "checks": [
            {
                "criterion": check.criterion,
                "required": check.required,
                "passed": check.passed,
                "details": check.details,
            }
            for check in checks
        ],
    }


def write_markdown_summary(path: Path, gate_result: dict[str, Any]) -> None:
    overall_pass = bool(gate_result["overall_pass"])
    checks = gate_result["checks"]

    lines = [
        "# Async Benchmark Release Gate",
        "",
        f"- Generated at (UTC): {gate_result['generated_at_utc']}",
        f"- Overall result: **{_bool_label(overall_pass)}**",
        "",
        "| Criterion | Required | Status | Details |",
        "|---|---|---|---|",
    ]
    for check in checks:
        required_label = "yes" if check["required"] else "no"
        status_label = _bool_label(bool(check["passed"]))
        lines.append(
            f"| {check['criterion']} | {required_label} | {status_label} | {check['details']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate async benchmark output (benchmark_results.json) against "
            "staging release-gate criteria and write summary artifacts."
        )
    )
    parser.add_argument(
        "--benchmark-results",
        required=True,
        help="Path to benchmark_results.json emitted by run_async_assessment_benchmark.py",
    )
    parser.add_argument(
        "--dataset-summary",
        help="Optional dataset_summary.json emitted by generate_async_benchmark_dataset.py",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory where release_gate_result.json and release_gate_summary.md are written",
    )
    parser.add_argument(
        "--min-total-entities",
        type=int,
        default=1000,
        help="Minimum required entity count in dataset_summary.json (default: 1000)",
    )
    parser.add_argument(
        "--baseline-p95-seconds",
        type=_parse_non_negative_float,
        help="Optional p95 completion-latency baseline to enforce regression threshold",
    )
    parser.add_argument(
        "--max-p95-regression-percent",
        type=_parse_non_negative_float,
        default=25.0,
        help="Allowed p95 latency regression percent over baseline (default: 25.0)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    benchmark_results_path = Path(args.benchmark_results)
    if not benchmark_results_path.exists():
        raise RuntimeError(f"benchmark results file not found: {benchmark_results_path}")

    output_dir = Path(args.output_dir) if args.output_dir else benchmark_results_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    benchmark_results = _load_json(benchmark_results_path)
    dataset_summary = _load_json(Path(args.dataset_summary)) if args.dataset_summary else None

    gate_result = evaluate_gate(
        benchmark_results=benchmark_results,
        dataset_summary=dataset_summary,
        min_total_entities=args.min_total_entities,
        baseline_p95_seconds=args.baseline_p95_seconds,
        max_p95_regression_percent=args.max_p95_regression_percent,
    )

    result_json_path = output_dir / "release_gate_result.json"
    result_markdown_path = output_dir / "release_gate_summary.md"
    result_json_path.write_text(json.dumps(gate_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown_summary(result_markdown_path, gate_result)

    print(f"Release gate result written to: {result_json_path}")
    print(f"Release gate summary written to: {result_markdown_path}")

    return 0 if bool(gate_result["overall_pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
