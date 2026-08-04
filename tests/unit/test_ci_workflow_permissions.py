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


def test_staging_validation_gate_preserves_triggers_and_staging_security() -> None:
    workflow = _workflow("staging-validation-gate.yml")

    assert "  workflow_dispatch:" in workflow
    assert '    - cron: "0 9 * * 1"' in workflow
    assert "      ENVIRONMENT: staging" in workflow
    assert "      RATE_LIMIT_BACKEND: redis" in workflow
    assert "RATE_LIMIT_URL=rediss://localhost:6380/0?" in workflow
    assert "ssl_ca_certs=${REDIS_TLS_CA_CERT_PATH}" in workflow
    assert "ssl_cert_reqs=required" in workflow
    assert "redis://localhost:6380" not in workflow


def test_staging_validation_gate_bootstraps_pinned_tls_redis() -> None:
    workflow = _workflow("staging-validation-gate.yml")
    bootstrap = workflow.split("      - name: Start ephemeral TLS Redis", 1)[1].split(
        "\n      - name:", 1
    )[0]

    redis_image = (
        "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
    )
    assert redis_image in bootstrap
    assert "openssl req -x509" in bootstrap
    assert "subjectAltName=DNS:localhost,IP:127.0.0.1" in bootstrap
    assert "--publish 127.0.0.1:6380:6379" in bootstrap
    assert "--tls-port 6379" in bootstrap
    assert "--port 0" in bootstrap
    assert "--tls-cert-file /tls/server.crt" in bootstrap
    assert "--tls-key-file /tls/server.key" in bootstrap
    assert "--tls-ca-cert-file /tls/ca.crt" in bootstrap
    assert "redis-cli --tls --cacert /tls/ca.crt" in bootstrap


def test_staging_validation_gate_always_cleans_tls_redis_secrets() -> None:
    workflow = _workflow("staging-validation-gate.yml")
    cleanup = workflow.split("      - name: Clean up ephemeral staging services", 1)[1].split(
        "\n      - name:", 1
    )[0]
    upload = workflow.split("      - name: Upload staging validation artifacts", 1)[1]

    assert "        if: always()" in cleanup
    assert 'docker rm --force "${REDIS_CONTAINER_NAME}"' in cleanup
    assert 'rm -rf "${REDIS_TLS_DIR}" "${AUTH_KEY_DIR}"' in cleanup
    assert "        if: always()" in upload
    assert "path: ${{ env.VALIDATION_ROOT }}" in upload
    assert "REDIS_TLS_DIR" not in upload
    assert "AUTH_KEY_DIR" not in upload


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
