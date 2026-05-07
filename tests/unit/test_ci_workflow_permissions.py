from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text()


def test_ci_workflow_uses_least_privilege_permissions() -> None:
    workflow = _workflow("ci.yml")

    assert "\npermissions:\n  contents: read\n" in workflow


def test_staging_validation_gate_uses_least_privilege_permissions() -> None:
    workflow = _workflow("staging-validation-gate.yml")

    assert "\npermissions:\n  contents: read\n" in workflow
