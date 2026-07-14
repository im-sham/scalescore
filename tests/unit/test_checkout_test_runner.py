from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run_tests.py"


def _copy_runner(repo: Path) -> Path:
    runner = repo / "scripts" / "run_tests.py"
    runner.parent.mkdir(parents=True)
    shutil.copy2(RUNNER, runner)
    return runner


def _run_runner(runner: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(runner), *args],
        cwd=runner.parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def foreign_checkout(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "foreign-checkout"
    expected_package = repo / "src" / "scalescore"
    expected_package.mkdir(parents=True)
    (expected_package / "__init__.py").write_text("FOREIGN_CHECKOUT = True\n")

    runner = _copy_runner(repo)
    sentinel = repo / "pytest-imported"
    (runner.parent / "pytest.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('pytest imported')\n"
        "raise RuntimeError('pytest must not be imported after a provenance failure')\n"
    )
    return runner, sentinel


def test_symlinked_checkout_source_is_rejected_before_pytest_import(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "symlinked-checkout"
    logical_source = repo / "src" / "scalescore"
    logical_source.parent.mkdir(parents=True)
    resolved_source = (ROOT / "src" / "scalescore").resolve()
    logical_source.symlink_to(resolved_source, target_is_directory=True)

    runner = _copy_runner(repo)
    sentinel = repo / "pytest-imported"
    (runner.parent / "pytest.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('pytest imported')\n"
        "raise RuntimeError('pytest must not be imported after a provenance failure')\n"
    )

    result = _run_runner(runner, "--collect-only")

    assert result.returncode == 2
    assert not sentinel.exists()
    assert f"Checkout source (logical): {logical_source}" in result.stderr
    assert f"Checkout source (resolved): {resolved_source}" in result.stderr


def test_foreign_checkout_is_rejected_before_pytest_import(
    foreign_checkout: tuple[Path, Path],
) -> None:
    runner, sentinel = foreign_checkout

    result = _run_runner(runner, "--collect-only")

    expected_source = runner.parents[1] / "src" / "scalescore"
    active_source = ROOT / "src" / "scalescore"
    assert result.returncode == 2
    assert not sentinel.exists()
    assert str(Path(sys.executable).resolve()) in result.stderr
    assert str(expected_source.resolve()) in result.stderr
    assert str(active_source.resolve()) in result.stderr
    assert "remove only this checkout's .venv" in result.stderr
    assert "Use Python 3.11 or newer; CI covers Python 3.11 and 3.12." in result.stderr
    assert "python -m venv .venv" in result.stderr
    venv_python = r".venv\Scripts\python.exe" if os.name == "nt" else ".venv/bin/python"
    assert f'{venv_python} -m pip install -e ".[dev]"' in result.stderr
    assert 'pip install -e ".[dev]"' in result.stderr


def test_runner_does_not_prepend_expected_source_to_sys_path(
    foreign_checkout: tuple[Path, Path],
) -> None:
    runner, sentinel = foreign_checkout

    result = _run_runner(runner, "--version")

    assert result.returncode == 2
    assert not sentinel.exists()
    assert "Checkout provenance check failed" in result.stderr


def test_unresolvable_package_path_is_rejected_before_pytest_import(tmp_path: Path) -> None:
    repo = tmp_path / "missing-module-path"
    (repo / "src" / "scalescore").mkdir(parents=True)
    runner = _copy_runner(repo)
    (runner.parent / "scalescore.py").write_text("__file__ = None\n")
    sentinel = repo / "pytest-imported"
    (runner.parent / "pytest.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('pytest imported')\n"
        "raise RuntimeError('pytest must not be imported after a provenance failure')\n"
    )

    result = _run_runner(runner, "--collect-only")

    assert result.returncode == 2
    assert not sentinel.exists()
    assert "Imported scalescore: unavailable" in result.stderr


def test_editable_checkout_reaches_pytest_and_returns_its_exit_code(tmp_path: Path) -> None:
    passing_test = tmp_path / "test_runner_delegate.py"
    passing_test.write_text("def test_delegated() -> None:\n    assert True\n")
    failing_test = tmp_path / "test_runner_failure.py"
    failing_test.write_text("def test_delegated_failure() -> None:\n    assert False\n")

    passing = _run_runner(RUNNER, "-q", str(passing_test))
    failing = _run_runner(RUNNER, "-q", str(failing_test))

    assert passing.returncode == 0, passing.stderr
    assert "1 passed" in passing.stdout
    assert failing.returncode == pytest.ExitCode.TESTS_FAILED
    assert "1 failed" in failing.stdout
