#!/usr/bin/env python3
"""Fail when mypy reports diagnostics outside the accepted debt baseline."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TypeAlias

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "typecheck-baseline.json"
DiagnosticKey: TypeAlias = tuple[str, str, str]
DiagnosticCounts: TypeAlias = dict[DiagnosticKey, int]


def diagnostic_counts(diagnostics: Iterable[object]) -> DiagnosticCounts:
    """Count stable diagnostic signatures, excluding line positions that may move."""
    counts: DiagnosticCounts = {}
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            raise ValueError("each mypy diagnostic must be a JSON object")
        path = diagnostic.get("file")
        code = diagnostic.get("code")
        message = diagnostic.get("message")
        if not all(isinstance(value, str) and value for value in (path, code, message)):
            raise ValueError("each mypy diagnostic requires non-empty file, code, and message")
        key = (path, code, message)
        counts[key] = counts.get(key, 0) + 1
    return counts


def unexpected_diagnostics(
    current: DiagnosticCounts,
    baseline: DiagnosticCounts,
) -> DiagnosticCounts:
    """Return diagnostic occurrences exceeding the accepted baseline."""
    return {
        key: count - baseline.get(key, 0)
        for key, count in sorted(current.items())
        if count > baseline.get(key, 0)
    }


def _load_baseline(path: Path = BASELINE) -> DiagnosticCounts:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("typecheck baseline must be a version 1 JSON object")
    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise ValueError("typecheck baseline diagnostics must be a JSON list")
    return diagnostic_counts(diagnostics)


def _parse_mypy_output(output: str) -> DiagnosticCounts:
    diagnostics: list[object] = []
    for line in output.splitlines():
        if line.strip():
            diagnostics.append(json.loads(line))
    return diagnostic_counts(diagnostics)


def main() -> int:
    try:
        baseline = _load_baseline()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"invalid mypy baseline: {error}", file=sys.stderr)
        return 2

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "src",
            "--output=json",
            "--no-error-summary",
            "--no-pretty",
            "--no-incremental",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode not in (0, 1):
        print(f"mypy failed unexpectedly with exit code {result.returncode}", file=sys.stderr)
        return result.returncode or 2

    try:
        current = _parse_mypy_output(result.stdout)
    except (ValueError, json.JSONDecodeError) as error:
        print(f"invalid mypy JSON output: {error}", file=sys.stderr)
        return 2
    if result.returncode == 1 and not current:
        print("mypy failed without emitting JSON diagnostics", file=sys.stderr)
        return 2

    unexpected = unexpected_diagnostics(current, baseline)
    if unexpected:
        print("new mypy diagnostics exceed the accepted baseline:", file=sys.stderr)
        for (path, code, message), count in unexpected.items():
            print(f"  {path}: [{code}] {message} (+{count})", file=sys.stderr)
        return 1

    print(
        "mypy baseline passed: "
        f"{sum(current.values())} current errors; "
        f"{sum(baseline.values())} accepted maximum"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
