#!/usr/bin/env python3
"""Compile or verify the ratified Linux x86_64 Python 3.12 production lock."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONSTRAINT = Path("constraints/linux-x86_64-python3.12-runtime.txt")
PRODUCTION_LOCK = Path("requirements/production-linux-x86_64-python3.12.txt")


class UnsupportedProductionTargetError(RuntimeError):
    """Raised when lock compilation runs outside the ratified target."""


class ProductionLockDriftError(RuntimeError):
    """Raised when the compiled production lock differs from the tracked lock."""


def _normalized_machine() -> str:
    machine = platform.machine().lower()
    return "x86_64" if machine == "amd64" else machine


def validate_target() -> None:
    """Fail unless compilation uses Linux x86_64 and Python 3.12."""
    version = (sys.version_info.major, sys.version_info.minor)
    system = platform.system().lower()
    machine = _normalized_machine()
    if (system, machine, version) != ("linux", "x86_64", (3, 12)):
        raise UnsupportedProductionTargetError(
            "production lock compilation requires Linux x86_64 with Python 3.12; "
            f"received {system}/{machine} Python {version[0]}.{version[1]}"
        )


def compile_command(*, root: Path, output: Path) -> list[str]:
    """Return the deterministic pip-tools command for the production lock."""
    return [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--quiet",
        "--resolver=backtracking",
        "--allow-unsafe",
        "--strip-extras",
        "--generate-hashes",
        "--reuse-hashes",
        "--no-header",
        "--no-annotate",
        "--no-emit-index-url",
        "--no-emit-trusted-host",
        "--no-emit-options",
        f"--constraint={root / RUNTIME_CONSTRAINT}",
        f"--output-file={output}",
        str(root / "pyproject.toml"),
    ]


def compile_lock(*, root: Path = ROOT, check: bool = False) -> None:
    """Generate the production lock or compare a fresh compilation with it."""
    validate_target()
    tracked = root / PRODUCTION_LOCK
    if not check:
        tracked.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(compile_command(root=root, output=tracked), check=True)
        return

    if not tracked.is_file():
        raise ProductionLockDriftError(f"tracked production lock is missing: {tracked}")

    with tempfile.TemporaryDirectory(prefix="scalescore-production-lock-") as temporary:
        candidate = Path(temporary) / tracked.name
        shutil.copyfile(tracked, candidate)
        subprocess.run(compile_command(root=root, output=candidate), check=True)
        if candidate.read_bytes() != tracked.read_bytes():
            raise ProductionLockDriftError(
                "production lock drift detected; regenerate on Linux x86_64 with Python 3.12"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without modifying the lock")
    arguments = parser.parse_args(argv)
    try:
        compile_lock(check=arguments.check)
    except (ProductionLockDriftError, UnsupportedProductionTargetError) as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
