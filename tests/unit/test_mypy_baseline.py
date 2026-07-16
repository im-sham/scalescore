from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_mypy_baseline.py"


def _load_checker():
    assert CHECKER.exists(), "mypy baseline checker must exist"
    spec = importlib.util.spec_from_file_location("mypy_baseline_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _diagnostic(*, path: str, code: str, message: str) -> dict[str, object]:
    return {
        "file": path,
        "line": 1,
        "column": 0,
        "message": message,
        "hint": None,
        "code": code,
        "severity": "error",
    }


def test_replacing_a_baselined_error_with_a_new_error_fails_without_count_growth() -> None:
    checker = _load_checker()
    baseline = checker.diagnostic_counts(
        [_diagnostic(path="src/example.py", code="old-code", message="old error")]
    )
    current = checker.diagnostic_counts(
        [_diagnostic(path="src/example.py", code="new-code", message="new error")]
    )

    assert checker.unexpected_diagnostics(current, baseline) == {
        ("src/example.py", "new-code", "new error"): 1
    }


def test_removed_diagnostics_and_lower_duplicate_counts_are_allowed() -> None:
    checker = _load_checker()
    diagnostic = _diagnostic(path="src/example.py", code="arg-type", message="bad argument")
    baseline = checker.diagnostic_counts([diagnostic, diagnostic])
    current = checker.diagnostic_counts([diagnostic])

    assert checker.unexpected_diagnostics(current, baseline) == {}
