#!/usr/bin/env python3
"""Build, install, and import WorkflowRef from outside the source checkout."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with TemporaryDirectory(prefix="scalescore-wheel-smoke-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        wheel_directory = temporary_root / "wheel"
        install_root = temporary_root / "install"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(wheel_directory),
            ],
            cwd=REPO_ROOT,
            check=True,
        )
        wheels = list(wheel_directory.glob("scalescore-*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"Expected one ScaleScore wheel, found {len(wheels)}")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(install_root),
                str(wheels[0]),
            ],
            cwd=temporary_root,
            check=True,
        )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        smoke_code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scalescore.contracts.generated import workflow_ref as generated
from scalescore.contracts.workflow_ref import WorkflowRefEnvelope
install_root = Path(sys.argv[1]).resolve()
assert Path(generated.__file__).resolve().is_relative_to(install_root)
envelope = WorkflowRefEnvelope.model_validate({
    "contract_version": "proofhouse-shared-contracts/v0.1",
    "contract_name": "WorkflowRef",
    "producer_capability": "workflow_context",
    "producer_system": "proofhouse-workflow-context",
    "canonical_owner": "workflow_context",
    "issued_at": "2026-07-30T12:00:00Z",
    "cache_policy": "ref_only",
    "ref": {
        "ref_id": "workflow:wf_wheel_smoke",
        "ref_type": "workflow",
        "source_capability": "workflow_context",
        "organization_id": "org_wheel_smoke",
        "environment_id": "test",
        "external_uri": "workflow-context://org_wheel_smoke/test/wf_wheel_smoke/snapshot_1",
        "snapshot_id": "snapshot_1",
        "version": "version_1",
        "created_at": "2026-07-30T11:00:00Z",
        "workflow_id": "wf_wheel_smoke",
    },
})
assert envelope.ref.snapshot_id == "snapshot_1"
"""
        subprocess.run(
            [sys.executable, "-c", smoke_code, str(install_root)],
            cwd=temporary_root,
            env=environment,
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
