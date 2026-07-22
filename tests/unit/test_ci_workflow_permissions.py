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


def test_staging_validation_uses_constrained_editable_install_without_source_bypass() -> None:
    workflow = _workflow("staging-validation-gate.yml")
    install_block = workflow.split("      - name: Install constrained dependencies", 1)[1].split(
        "\n      - name:", 1
    )[0]
    constraint = "constraints/linux-x86_64-python3.12-dev.txt"
    pip_floor = f"python -m pip install --upgrade --constraint {constraint} 'pip>=26.0.1'"
    editable_install = f'python -m pip install --constraint {constraint} -e ".[dev]"'
    pip_check = "python -m pip check"

    assert pip_floor in install_block
    assert editable_install in install_block
    assert pip_check in install_block
    assert install_block.index(pip_floor) < install_block.index(editable_install)
    assert install_block.index(editable_install) < install_block.index(pip_check)
    assert "PYTHONPATH" not in workflow


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
    assert matrix_job.count("fetch-depth: 0") == 1
    dev_install = (
        'python -m pip install --constraint "constraints/linux-x86_64-python'
        '${{ matrix.python-version }}-dev.txt" -e ".[dev]"'
    )
    assert matrix_job.count(dev_install) == 1
    assert ".[dev,frontend]" not in matrix_job
    assert matrix_job.count("TRUSTED_BASE_REF:") == 1
    assert "github.event.pull_request.base.sha" in matrix_job
    assert "github.event.before" in matrix_job
    expected_command = 'python scripts/check_mypy_baseline.py --base-ref "$TRUSTED_BASE_REF"'
    assert matrix_job.count(expected_command) == 1
    assert matrix_job.index(dev_install) < matrix_job.index(expected_command)
    assert workflow.count(expected_command) == 1
