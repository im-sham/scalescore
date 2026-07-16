from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAGGED_ACTION_REF = re.compile(r"uses:\s+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@v\d+")


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text()


def test_ci_workflow_uses_least_privilege_permissions() -> None:
    workflow = _workflow("ci.yml")

    assert "\npermissions:\n  contents: read\n" in workflow


def test_staging_validation_gate_uses_least_privilege_permissions() -> None:
    workflow = _workflow("staging-validation-gate.yml")

    assert "\npermissions:\n  contents: read\n" in workflow


def test_github_actions_are_pinned_to_commit_shas() -> None:
    offenders: list[str] = []
    for name in ("ci.yml", "staging-validation-gate.yml"):
        offenders.extend(
            f"{name}: {line.strip()}"
            for line in _workflow(name).splitlines()
            if TAGGED_ACTION_REF.search(line)
        )

    assert offenders == []


def test_dependabot_tracks_ci_and_python_updates() -> None:
    config = ROOT / ".github" / "dependabot.yml"

    assert config.exists()
    content = config.read_text()
    assert 'package-ecosystem: "github-actions"' in content
    assert 'package-ecosystem: "pip"' in content


def test_ci_matrix_blocks_new_mypy_diagnostics() -> None:
    workflow = _workflow("ci.yml")
    matrix_job = workflow.split("\n  redis-rate-limit-integration:", maxsplit=1)[0]

    assert matrix_job.count("name: Lint and Test (Python ${{ matrix.python-version }})") == 1
    assert matrix_job.count("run: python scripts/check_mypy_baseline.py") == 1
    assert workflow.count("run: python scripts/check_mypy_baseline.py") == 1
