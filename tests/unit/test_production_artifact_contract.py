from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_LOCK = ROOT / "requirements" / "production-linux-x86_64-python3.12.txt"
IMAGE_WORKFLOW = ROOT / ".github" / "workflows" / "image.yml"
PARITY_SCRIPT = ROOT / "scripts" / "verify_runtime_sbom_parity.py"
PIN_WITH_HASH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^;\s]+(?:\s*;\s*[^#\s].*)? \\$")
HASH = re.compile(r"^    --hash=sha256:[0-9a-f]{64}(?: \\)?$")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ratified_topology_is_recorded_as_an_accepted_adr() -> None:
    adr = (ROOT / "docs" / "adr" / "0018-production-container-artifact.md").read_text()

    assert "**Status**: Accepted" in adr
    assert "Linux x86_64" in adr
    assert "Python 3.12" in adr
    assert "one shared core image" in adr
    assert "API" in adr and "worker" in adr
    assert "Streamlit" in adr and "excluded" in adr
    assert "orchestration" in adr and "provider" in adr


def test_production_lock_is_hash_pinned_and_excludes_frontend() -> None:
    lines = [
        line
        for line in PRODUCTION_LOCK.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    package_lines = [line for line in lines if not line.startswith("    ")]
    hash_lines = [line for line in lines if line.startswith("    ")]

    assert package_lines
    assert all(PIN_WITH_HASH.fullmatch(line) for line in package_lines)
    assert all(HASH.fullmatch(line) for line in hash_lines)
    assert len(hash_lines) >= len(package_lines)
    runtime_pins = {
        line
        for line in (ROOT / "constraints" / "linux-x86_64-python3.12-runtime.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#")
    }
    assert {line.removesuffix(" \\") for line in package_lines} == runtime_pins
    assert not {"plotly", "protobuf", "streamlit", "watchdog"} & {
        line.split("==", 1)[0].lower() for line in package_lines
    }


def test_production_lock_compiler_is_fixed_to_ratified_target() -> None:
    compiler = _load_module(
        ROOT / "scripts" / "compile_production_lock.py",
        "production_lock_compiler",
    )
    command = compiler.compile_command(
        root=Path("/checkout"),
        output=Path("/tmp/production.txt"),
    )

    assert "--generate-hashes" in command
    assert "--constraint=/checkout/constraints/linux-x86_64-python3.12-runtime.txt" in command
    assert "--output-file=/tmp/production.txt" in command
    assert command[-1] == "/checkout/pyproject.toml"


def test_shared_image_is_pinned_non_root_and_has_explicit_commands() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "python:3.12.13-slim-trixie@sha256:" in dockerfile
    assert "--platform=linux/amd64" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "production-linux-x86_64-python3.12.txt" in dockerfile
    assert "rm -rf /usr/local/lib/python3.12/site-packages" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/scalescore-container"]' in dockerfile
    assert 'CMD ["api"]' in dockerfile
    assert "frontend" not in dockerfile.lower()
    assert '"api")' in entrypoint
    assert '"worker")' in entrypoint
    assert "uvicorn scalescore.api.main:app" in entrypoint
    assert "exec scalescore-worker" in entrypoint


def test_image_workflow_builds_smokes_attests_scans_and_retains() -> None:
    workflow = IMAGE_WORKFLOW.read_text(encoding="utf-8")

    required = (
        "permissions:\n  contents: read",
        "platforms: linux/amd64",
        "load: true",
        "/api/v1/health",
        "worker --help",
        "runtime-inventory.json",
        "cyclonedx-json",
        "verify_runtime_sbom_parity.py",
        "anchore/scan-action@",
        "fail-build: true",
        "severity-cutoff: high",
        "only-fixed: false",
        "docker save",
        "sha256sum",
        "retention-days: 30",
    )
    assert all(value in workflow for value in required)
    prohibited = ("only-fixed: true", "severity-cutoff: critical", "vex:", ".grype.yaml")
    assert all(value not in workflow for value in prohibited)


def test_runtime_inventory_and_sbom_require_bidirectional_version_parity(tmp_path: Path) -> None:
    verifier = _load_module(PARITY_SCRIPT, "runtime_sbom_parity")
    inventory = tmp_path / "inventory.json"
    sbom = tmp_path / "sbom.json"
    inventory.write_text(
        json.dumps([{"name": "Example_Package", "version": "1.2.3"}]),
        encoding="utf-8",
    )
    sbom.write_text(
        json.dumps(
            {
                "components": [
                    {
                        "type": "library",
                        "name": "example-package",
                        "version": "1.2.3",
                        "purl": "pkg:pypi/example-package@1.2.3",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert verifier.verify_parity(inventory, sbom) == (set(), set())

    sbom.write_text(json.dumps({"components": []}), encoding="utf-8")
    inventory_only, sbom_only = verifier.verify_parity(inventory, sbom)
    assert inventory_only == {("example-package", "1.2.3")}
    assert sbom_only == set()


def test_runtime_inventory_and_sbom_reject_duplicate_python_components(tmp_path: Path) -> None:
    verifier = _load_module(PARITY_SCRIPT, "runtime_sbom_duplicate_check")
    inventory = tmp_path / "inventory.json"
    sbom = tmp_path / "sbom.json"
    inventory.write_text(json.dumps([{"name": "demo", "version": "1.0"}]), encoding="utf-8")
    component = {
        "type": "library",
        "name": "demo",
        "version": "1.0",
        "purl": "pkg:pypi/demo@1.0",
    }
    sbom.write_text(json.dumps({"components": [component, component]}), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        verifier.verify_parity(inventory, sbom)
