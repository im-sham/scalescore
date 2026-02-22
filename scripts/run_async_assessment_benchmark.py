#!/usr/bin/env python3
"""Run async assessment upload/poll benchmarks and collect validation evidence."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

REQUIRED_DATASET_FILES = (
    "organizations.csv",
    "teams.csv",
    "systems.csv",
    "vendors.csv",
    "facilities.csv",
    "growth_signals.csv",
)

TERMINAL_STATUSES = {"completed", "failed"}


@dataclass
class JobTrace:
    job_id: str
    submit_status_code: int
    submit_latency_seconds: float
    submitted_at_utc: str
    submitted_perf_counter: float
    status_history: list[dict[str, object]] = field(default_factory=list)
    terminal_status: str | None = None
    report_id: str | None = None
    org_id: str | None = None
    error_message: str | None = None
    completed_at_utc: str | None = None
    completion_latency_seconds: float | None = None
    timed_out: bool = False


@dataclass
class BenchmarkConfig:
    base_url: str
    dataset_dir: Path
    jobs: int
    poll_interval_seconds: float
    timeout_seconds: float
    request_timeout_seconds: float
    output_dir: Path
    verify_tls: bool


def _parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def _parse_positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def _default_output_dir() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(".local/performance/benchmarks") / f"async-assessment-{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark async assessment upload and completion for large datasets."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", "http://localhost:8000"),
        help="ScaleScore API base URL",
    )
    parser.add_argument(
        "--dataset-dir",
        required=True,
        help="Directory containing organizations.csv, teams.csv, systems.csv, vendors.csv, facilities.csv, growth_signals.csv",
    )
    parser.add_argument(
        "--access-token",
        default=os.environ.get("ACCESS_TOKEN"),
        help="Bearer token; optional if AUTH_SKIP_AUTH=true",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("API_KEY"),
        help="API key alternative to Bearer token",
    )
    parser.add_argument("--jobs", type=_parse_positive_int, default=3)
    parser.add_argument("--poll-interval-seconds", type=_parse_positive_float, default=0.5)
    parser.add_argument("--timeout-seconds", type=_parse_positive_float, default=900.0)
    parser.add_argument("--request-timeout-seconds", type=_parse_positive_float, default=30.0)
    parser.add_argument(
        "--output-dir",
        default=str(_default_output_dir()),
        help="Directory where benchmark artifacts are written",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification",
    )
    return parser.parse_args()


def _require_dataset(dataset_dir: Path) -> None:
    missing = [name for name in REQUIRED_DATASET_FILES if not (dataset_dir / name).exists()]
    if missing:
        raise RuntimeError(f"dataset is missing required files: {', '.join(missing)}")


def _build_headers(access_token: str | None, api_key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    elif api_key:
        headers["X-API-Key"] = api_key
    return headers


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def _post_async_job(
    client: httpx.Client,
    *,
    dataset_dir: Path,
    headers: dict[str, str],
    request_timeout_seconds: float,
) -> tuple[str, int, float, str]:
    files = {
        "organizations": ("organizations.csv", (dataset_dir / "organizations.csv").read_bytes(), "text/csv"),
        "teams": ("teams.csv", (dataset_dir / "teams.csv").read_bytes(), "text/csv"),
        "systems": ("systems.csv", (dataset_dir / "systems.csv").read_bytes(), "text/csv"),
        "vendors": ("vendors.csv", (dataset_dir / "vendors.csv").read_bytes(), "text/csv"),
        "facilities": ("facilities.csv", (dataset_dir / "facilities.csv").read_bytes(), "text/csv"),
        "growth_signals": (
            "growth_signals.csv",
            (dataset_dir / "growth_signals.csv").read_bytes(),
            "text/csv",
        ),
    }

    submit_started = time.perf_counter()
    response = client.post(
        "/api/v1/assessments/async/upload",
        files=files,
        headers=headers,
        timeout=request_timeout_seconds,
    )
    submit_latency = time.perf_counter() - submit_started
    submit_timestamp_utc = datetime.now(UTC).isoformat()

    if response.status_code != 202:
        response_text = response.text.strip()
        raise RuntimeError(
            "async upload returned unexpected response: "
            f"status={response.status_code}, body={response_text}"
        )

    payload = response.json()
    job_id = str(payload.get("job_id", "")).strip()
    if not job_id:
        raise RuntimeError("async upload response did not include job_id")

    return job_id, response.status_code, submit_latency, submit_timestamp_utc


def _poll_async_job(
    client: httpx.Client,
    *,
    job_id: str,
    headers: dict[str, str],
    request_timeout_seconds: float,
) -> dict[str, object]:
    response = client.get(
        f"/api/v1/assessments/async/{job_id}",
        headers=headers,
        timeout=request_timeout_seconds,
    )
    if response.status_code != 200:
        response_text = response.text.strip()
        raise RuntimeError(
            "async poll returned unexpected response: "
            f"status={response.status_code}, body={response_text}"
        )
    payload = response.json()
    status_value = str(payload.get("status", "")).strip()
    if not status_value:
        raise RuntimeError(f"async poll for job={job_id} did not include status")
    return payload


def run_benchmark(
    config: BenchmarkConfig,
    *,
    access_token: str | None,
    api_key: str | None,
) -> dict[str, object]:
    _require_dataset(config.dataset_dir)

    headers = _build_headers(access_token, api_key)
    traces: dict[str, JobTrace] = {}

    benchmark_started_at_utc = datetime.now(UTC).isoformat()
    benchmark_started = time.perf_counter()

    with httpx.Client(base_url=config.base_url, verify=config.verify_tls) as client:
        for index in range(config.jobs):
            job_id, status_code, submit_latency, submitted_at_utc = _post_async_job(
                client,
                dataset_dir=config.dataset_dir,
                headers=headers,
                request_timeout_seconds=config.request_timeout_seconds,
            )
            trace = JobTrace(
                job_id=job_id,
                submit_status_code=status_code,
                submit_latency_seconds=submit_latency,
                submitted_at_utc=submitted_at_utc,
                submitted_perf_counter=time.perf_counter(),
            )
            traces[job_id] = trace
            print(
                f"[{index + 1}/{config.jobs}] submitted job_id={job_id} "
                f"submit_latency={submit_latency:.3f}s"
            )

        pending = set(traces.keys())
        while pending:
            elapsed = time.perf_counter() - benchmark_started
            if elapsed >= config.timeout_seconds:
                for job_id in pending:
                    traces[job_id].timed_out = True
                break

            for job_id in list(pending):
                try:
                    payload = _poll_async_job(
                        client,
                        job_id=job_id,
                        headers=headers,
                        request_timeout_seconds=config.request_timeout_seconds,
                    )
                except Exception as err:  # noqa: BLE001
                    now_utc = datetime.now(UTC).isoformat()
                    now_perf = time.perf_counter()
                    traces[job_id].status_history.append(
                        {
                            "timestamp_utc": now_utc,
                            "status": "poll_error",
                            "progress_stage": "poll_error",
                            "progress_percentage": 0,
                            "progress_message": str(err),
                        }
                    )
                    traces[job_id].terminal_status = "failed"
                    traces[job_id].error_message = str(err)
                    traces[job_id].completed_at_utc = now_utc
                    traces[job_id].completion_latency_seconds = (
                        now_perf - traces[job_id].submitted_perf_counter
                    )
                    pending.remove(job_id)
                    continue
                status_value = str(payload.get("status", "")).strip()
                stage = str(payload.get("progress_stage", ""))
                percentage = int(payload.get("progress_percentage", 0))
                message = payload.get("progress_message")
                traces[job_id].status_history.append(
                    {
                        "timestamp_utc": datetime.now(UTC).isoformat(),
                        "status": status_value,
                        "progress_stage": stage,
                        "progress_percentage": percentage,
                        "progress_message": message,
                    }
                )

                if status_value in TERMINAL_STATUSES:
                    now_utc = datetime.now(UTC).isoformat()
                    now_perf = time.perf_counter()
                    traces[job_id].terminal_status = status_value
                    traces[job_id].completed_at_utc = now_utc
                    traces[job_id].completion_latency_seconds = (
                        now_perf - traces[job_id].submitted_perf_counter
                    )
                    traces[job_id].report_id = _nullable_string(payload.get("report_id"))
                    traces[job_id].org_id = _nullable_string(payload.get("org_id"))
                    traces[job_id].error_message = _nullable_string(payload.get("error_message"))
                    pending.remove(job_id)

            if pending:
                time.sleep(config.poll_interval_seconds)

    benchmark_finished = time.perf_counter()
    benchmark_finished_at_utc = datetime.now(UTC).isoformat()

    for trace in traces.values():
        if trace.timed_out and trace.terminal_status is None:
            trace.terminal_status = "timed_out"

    submit_latencies = [trace.submit_latency_seconds for trace in traces.values()]
    completion_latencies = [
        trace.completion_latency_seconds
        for trace in traces.values()
        if trace.completion_latency_seconds is not None
    ]

    completed_jobs = [trace for trace in traces.values() if trace.terminal_status == "completed"]
    failed_jobs = [trace for trace in traces.values() if trace.terminal_status == "failed"]
    timed_out_jobs = [trace for trace in traces.values() if trace.terminal_status == "timed_out"]

    summary = {
        "benchmark_started_at_utc": benchmark_started_at_utc,
        "benchmark_finished_at_utc": benchmark_finished_at_utc,
        "duration_seconds": _rounded(benchmark_finished - benchmark_started),
        "config": {
            "base_url": config.base_url,
            "dataset_dir": str(config.dataset_dir),
            "jobs": config.jobs,
            "poll_interval_seconds": config.poll_interval_seconds,
            "timeout_seconds": config.timeout_seconds,
            "request_timeout_seconds": config.request_timeout_seconds,
            "verify_tls": config.verify_tls,
            "used_authorization": bool(access_token or api_key),
        },
        "results": {
            "submitted_jobs": len(traces),
            "completed_jobs": len(completed_jobs),
            "failed_jobs": len(failed_jobs),
            "timed_out_jobs": len(timed_out_jobs),
            "submit_latency_seconds": {
                "mean": _rounded(statistics.fmean(submit_latencies)) if submit_latencies else None,
                "median": _rounded(statistics.median(submit_latencies)) if submit_latencies else None,
                "p95": _rounded(_percentile(submit_latencies, 0.95)),
            },
            "completion_latency_seconds": {
                "mean": _rounded(statistics.fmean(completion_latencies))
                if completion_latencies
                else None,
                "median": _rounded(statistics.median(completion_latencies))
                if completion_latencies
                else None,
                "p95": _rounded(_percentile(completion_latencies, 0.95)),
            },
            "throughput_jobs_per_minute": _rounded(
                (len(completed_jobs) / max(benchmark_finished - benchmark_started, 1e-9)) * 60.0
            ),
        },
        "jobs": [
            {
                "job_id": trace.job_id,
                "submit_status_code": trace.submit_status_code,
                "submit_latency_seconds": _rounded(trace.submit_latency_seconds),
                "submitted_at_utc": trace.submitted_at_utc,
                "terminal_status": trace.terminal_status,
                "report_id": trace.report_id,
                "org_id": trace.org_id,
                "error_message": trace.error_message,
                "completed_at_utc": trace.completed_at_utc,
                "completion_latency_seconds": _rounded(trace.completion_latency_seconds),
                "timed_out": trace.timed_out,
                "status_history": trace.status_history,
            }
            for trace in sorted(traces.values(), key=lambda item: item.job_id)
        ],
    }

    return summary


def _nullable_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _write_summary_markdown(path: Path, summary: dict[str, object]) -> None:
    results = summary["results"]
    submit_latency = results["submit_latency_seconds"]
    completion_latency = results["completion_latency_seconds"]
    config = summary["config"]

    markdown = "\n".join(
        [
            "# Async Assessment Benchmark Summary",
            "",
            f"- Benchmark started (UTC): {summary['benchmark_started_at_utc']}",
            f"- Benchmark finished (UTC): {summary['benchmark_finished_at_utc']}",
            f"- Duration (seconds): {summary['duration_seconds']}",
            f"- Base URL: {config['base_url']}",
            f"- Dataset directory: {config['dataset_dir']}",
            f"- Jobs requested: {config['jobs']}",
            "",
            "## Results",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| submitted_jobs | {results['submitted_jobs']} |",
            f"| completed_jobs | {results['completed_jobs']} |",
            f"| failed_jobs | {results['failed_jobs']} |",
            f"| timed_out_jobs | {results['timed_out_jobs']} |",
            f"| submit_mean_seconds | {submit_latency['mean']} |",
            f"| submit_median_seconds | {submit_latency['median']} |",
            f"| submit_p95_seconds | {submit_latency['p95']} |",
            f"| completion_mean_seconds | {completion_latency['mean']} |",
            f"| completion_median_seconds | {completion_latency['median']} |",
            f"| completion_p95_seconds | {completion_latency['p95']} |",
            f"| throughput_jobs_per_minute | {results['throughput_jobs_per_minute']} |",
            "",
            "## Exit Gate",
            "",
            "Pass when all jobs complete with `terminal_status=completed` and `failed_jobs=0` and `timed_out_jobs=0`.",
        ]
    )
    path.write_text(markdown + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    config = BenchmarkConfig(
        base_url=args.base_url.rstrip("/"),
        dataset_dir=Path(args.dataset_dir),
        jobs=args.jobs,
        poll_interval_seconds=args.poll_interval_seconds,
        timeout_seconds=args.timeout_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        output_dir=Path(args.output_dir),
        verify_tls=not args.insecure,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)

    summary = run_benchmark(
        config,
        access_token=args.access_token,
        api_key=args.api_key,
    )

    json_path = config.output_dir / "benchmark_results.json"
    markdown_path = config.output_dir / "benchmark_summary.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_summary_markdown(markdown_path, summary)

    print(f"Benchmark results written to: {json_path}")
    print(f"Benchmark summary written to: {markdown_path}")

    failed_jobs = int(summary["results"]["failed_jobs"])
    timed_out_jobs = int(summary["results"]["timed_out_jobs"])
    completed_jobs = int(summary["results"]["completed_jobs"])
    submitted_jobs = int(summary["results"]["submitted_jobs"])

    if failed_jobs > 0 or timed_out_jobs > 0 or completed_jobs != submitted_jobs:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
