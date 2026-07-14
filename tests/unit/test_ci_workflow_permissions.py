from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_CONSTRAINTS = ROOT / "constraints.txt"
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


def test_ci_installs_project_dependencies_with_python_constraints() -> None:
    workflow = _workflow("ci.yml")

    assert 'pip install -c constraints.txt -e ".[dev]"' in workflow


def test_dependency_security_audits_pinned_python_constraints() -> None:
    workflow = _workflow("ci.yml")

    assert "pip-audit --progress-spinner off -r constraints.txt" in workflow


def test_python_constraints_pin_ci_dependency_set() -> None:
    assert PYTHON_CONSTRAINTS.exists()
    content = PYTHON_CONSTRAINTS.read_text()

    for package in (
        "cryptography",
        "fastapi",
        "pandas",
        "pydantic",
        "pytest",
        "ruff",
        "streamlit",
    ):
        assert f"{package}==" in content.lower()

    unconstrained_lines = [
        line
        for line in content.splitlines()
        if line.strip() and not line.startswith("#") and "==" not in line
    ]
    assert unconstrained_lines == []
