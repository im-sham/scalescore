from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def _write_baseline(path: Path, diagnostics: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"version": 1, "diagnostics": diagnostics}))


def _init_git_repository(path: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Baseline Test",
            "-c",
            "user.email=baseline@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "base",
        ],
        cwd=path,
        check=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_main(
    checker,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    candidate: list[dict[str, object]],
    current: list[dict[str, object]],
    trusted: list[dict[str, object]] | None,
) -> int:
    baseline = tmp_path / "typecheck-baseline.json"
    _write_baseline(baseline, candidate)
    monkeypatch.setattr(checker, "BASELINE", baseline)
    monkeypatch.setattr(
        checker,
        "_load_trusted_baseline",
        lambda _base_ref: None if trusted is None else checker.diagnostic_counts(trusted),
    )
    stdout = "\n".join(json.dumps(diagnostic) for diagnostic in current)
    monkeypatch.setattr(
        checker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1 if current else 0,
            stdout=stdout,
            stderr="",
        ),
    )
    return checker.main(["--base-ref", "trusted"])


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


def test_candidate_baseline_inflation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_checker()
    new_diagnostic = _diagnostic(path="src/example.py", code="return-value", message="wrong return")

    assert (
        _run_main(
            checker,
            monkeypatch,
            tmp_path,
            candidate=[new_diagnostic],
            current=[new_diagnostic],
            trusted=[],
        )
        == 1
    )


def test_reduced_diagnostics_require_candidate_baseline_ratchet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_checker()
    diagnostic = _diagnostic(path="src/example.py", code="arg-type", message="bad argument")

    assert (
        _run_main(
            checker,
            monkeypatch,
            tmp_path,
            candidate=[diagnostic, diagnostic],
            current=[diagnostic],
            trusted=[diagnostic, diagnostic],
        )
        == 1
    )


def test_bootstrap_allows_exact_candidate_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_checker()
    diagnostic = _diagnostic(path="src/example.py", code="arg-type", message="bad argument")

    assert (
        _run_main(
            checker,
            monkeypatch,
            tmp_path,
            candidate=[diagnostic],
            current=[diagnostic],
            trusted=None,
        )
        == 0
    )


def test_trusted_baseline_rejects_candidate_additions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_checker()
    old = _diagnostic(path="src/example.py", code="old-code", message="old error")
    new = _diagnostic(path="src/example.py", code="new-code", message="new error")

    assert (
        _run_main(
            checker,
            monkeypatch,
            tmp_path,
            candidate=[old, new],
            current=[old, new],
            trusted=[old],
        )
        == 1
    )


def test_valid_base_without_baseline_is_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker()
    base_ref = _init_git_repository(tmp_path)
    monkeypatch.setattr(checker, "ROOT", tmp_path)

    assert checker._load_trusted_baseline(base_ref) is None


def test_invalid_base_ref_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _load_checker()
    _init_git_repository(tmp_path)
    monkeypatch.setattr(checker, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="invalid trusted base ref"):
        checker._load_trusted_baseline("does-not-exist")


def test_complete_main_path_rejects_deliberate_wrong_return_diagnostic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checker = _load_checker()
    wrong_return = _diagnostic(
        path="src/scalescore/core/example.py",
        code="return-value",
        message='Incompatible return value type (got "str", expected "int")',
    )

    assert (
        _run_main(
            checker,
            monkeypatch,
            tmp_path,
            candidate=[],
            current=[wrong_return],
            trusted=[],
        )
        == 1
    )
