#!/usr/bin/env python3
"""Fail when mypy reports diagnostics outside the accepted debt baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TypeAlias, cast

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
        diagnostic_map = cast(Mapping[str, object], diagnostic)
        path = diagnostic_map.get("file")
        code = diagnostic_map.get("code")
        message = diagnostic_map.get("message")
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(code, str)
            or not code
            or not isinstance(message, str)
            or not message
        ):
            raise ValueError("each mypy diagnostic requires non-empty file, code, and message")
        key: DiagnosticKey = (path, code, message)
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


def _baseline_from_text(text: str) -> DiagnosticCounts:
    payload = cast(object, json.loads(text))
    if not isinstance(payload, dict):
        raise ValueError("typecheck baseline must be a version 1 JSON object")
    payload_map = cast(dict[str, object], payload)
    if payload_map.get("version") != 1:
        raise ValueError("typecheck baseline must be a version 1 JSON object")
    diagnostics = payload_map.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise ValueError("typecheck baseline diagnostics must be a JSON list")
    return diagnostic_counts(cast(list[object], diagnostics))


def _load_baseline(path: Path | None = None) -> DiagnosticCounts:
    return _baseline_from_text((path or BASELINE).read_text(encoding="utf-8"))


def _load_trusted_baseline(base_ref: str) -> DiagnosticCounts | None:
    verified = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if verified.returncode != 0:
        raise ValueError(f"invalid trusted base ref: {base_ref}")
    verified_commit = verified.stdout.strip()

    baseline_entry = subprocess.run(
        [
            "git",
            "ls-tree",
            "--name-only",
            "--full-tree",
            "-z",
            verified_commit,
            "--",
            BASELINE.name,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if baseline_entry.returncode != 0:
        raise ValueError(f"failed to inspect trusted base tree {verified_commit}")
    if not baseline_entry.stdout:
        return None
    if baseline_entry.stdout != f"{BASELINE.name}\0":
        raise ValueError(f"ambiguous baseline path in trusted base tree {verified_commit}")

    baseline_at_base = subprocess.run(
        ["git", "show", f"{verified_commit}:{BASELINE.name}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if baseline_at_base.returncode != 0:
        raise ValueError(f"failed to read {BASELINE.name} from trusted base {verified_commit}")
    return _baseline_from_text(baseline_at_base.stdout)


def _parse_mypy_output(output: str) -> DiagnosticCounts:
    diagnostics: list[object] = []
    for line in output.splitlines():
        if line.strip():
            diagnostics.append(cast(object, json.loads(line)))
    return diagnostic_counts(diagnostics)


def _print_diagnostics(title: str, diagnostics: DiagnosticCounts) -> None:
    print(title, file=sys.stderr)
    for (path, code, message), count in diagnostics.items():
        print(f"  {path}: [{code}] {message} (+{count})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--base-ref", required=True)
    args = parser.parse_args(argv)
    base_ref = cast(str, args.base_ref)

    try:
        candidate = _load_baseline()
        trusted = _load_trusted_baseline(base_ref)
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

    additions = unexpected_diagnostics(current, candidate)
    stale = unexpected_diagnostics(candidate, current)
    if additions:
        _print_diagnostics(
            "current mypy diagnostics missing from the candidate baseline:", additions
        )
    if stale:
        _print_diagnostics("candidate baseline contains stale excess diagnostics:", stale)
    if additions or stale:
        return 1

    if trusted is not None:
        growth = unexpected_diagnostics(candidate, trusted)
        if growth:
            _print_diagnostics("candidate baseline exceeds the trusted base baseline:", growth)
            return 1

    bootstrap = " (trusted base has no baseline; bootstrap accepted)" if trusted is None else ""
    print(f"mypy baseline passed: {sum(current.values())} exact diagnostics{bootstrap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
