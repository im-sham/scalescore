#!/usr/bin/env python3
"""Compile or verify constraints for the active supported target environment."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PYTHON = {(3, 11): "3.11", (3, 12): "3.12"}
SUPPORTED_TARGETS = {
    ("darwin", "arm64"): "darwin-arm64",
    ("linux", "x86_64"): "linux-x86_64",
}
ARCHITECTURE_ALIASES = {
    "aarch64": "arm64",
    "amd64": "x86_64",
    "arm64": "arm64",
    "x86_64": "x86_64",
}
KINDS = ("runtime", "dev", "frontend")
Runner = Callable[[Sequence[str]], None]


class UnsupportedTargetError(RuntimeError):
    """Raised when compilation uses an unsupported target environment."""


class ConstraintDriftError(RuntimeError):
    """Raised when compiled dependencies differ from tracked constraints."""


def constraint_paths(
    version_info: tuple[int, int],
    *,
    system: str | None = None,
    machine: str | None = None,
    root: Path = ROOT,
) -> dict[str, Path]:
    """Return constraint paths for the supported active target environment."""
    try:
        minor = SUPPORTED_PYTHON[version_info]
    except KeyError as error:
        raise UnsupportedTargetError(
            "Constraint compilation requires Python 3.11 or 3.12; "
            f"received Python {version_info[0]}.{version_info[1]}."
        ) from error

    active_system = (system or platform.system()).lower()
    reported_machine = (machine or platform.machine()).lower()
    active_machine = ARCHITECTURE_ALIASES.get(reported_machine, reported_machine)
    try:
        target = SUPPORTED_TARGETS[(active_system, active_machine)]
    except KeyError as error:
        raise UnsupportedTargetError(
            "Constraint compilation received unsupported target environment "
            f"{active_system}/{reported_machine}; supported targets are "
            "Darwin arm64 and Linux x86_64."
        ) from error

    return {kind: root / "constraints" / f"{target}-python{minor}-{kind}.txt" for kind in KINDS}


def _run(command: Sequence[str]) -> None:
    subprocess.run(command, check=True)


def _compile_command(
    *,
    root: Path,
    output: Path,
    kind: str,
    upgrade: bool,
    upgrade_package: str | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--quiet",
        "--resolver=backtracking",
        "--allow-unsafe",
        "--strip-extras",
        "--no-header",
        "--no-annotate",
        "--no-emit-index-url",
        "--no-emit-trusted-host",
        f"--output-file={output}",
    ]
    if upgrade_package is not None:
        command.append(f"--upgrade-package={upgrade_package}")
    elif upgrade:
        command.append("--upgrade")
    if kind != "runtime":
        command.append(f"--extra={kind}")
    command.append(str(root / "pyproject.toml"))
    return command


def compile_constraints(
    *,
    root: Path = ROOT,
    version_info: tuple[int, int] | None = None,
    system: str | None = None,
    machine: str | None = None,
    check: bool = False,
    upgrade_package: str | None = None,
    runner: Runner = _run,
) -> None:
    """Compile or verify the active target environment and Python-minor pair."""
    active_version = version_info or (sys.version_info.major, sys.version_info.minor)
    tracked_paths = constraint_paths(
        active_version,
        system=system,
        machine=machine,
        root=root,
    )

    if not check:
        (root / "constraints").mkdir(parents=True, exist_ok=True)
        for kind, output in tracked_paths.items():
            runner(
                _compile_command(
                    root=root,
                    output=output,
                    kind=kind,
                    upgrade=upgrade_package is None,
                    upgrade_package=upgrade_package,
                )
            )
        return

    missing = [str(path) for path in tracked_paths.values() if not path.is_file()]
    if missing:
        raise ConstraintDriftError("Tracked constraint files are missing: " + ", ".join(missing))

    drifted: list[str] = []
    with tempfile.TemporaryDirectory(prefix="scalescore-constraints-") as temporary:
        temporary_dir = Path(temporary)
        for kind, tracked in tracked_paths.items():
            candidate = temporary_dir / tracked.name
            shutil.copyfile(tracked, candidate)
            runner(
                _compile_command(
                    root=root,
                    output=candidate,
                    kind=kind,
                    upgrade=False,
                )
            )
            if candidate.read_bytes() != tracked.read_bytes():
                drifted.append(str(tracked.relative_to(root)))

    if drifted:
        raise ConstraintDriftError(
            "Dependency constraint drift detected for the active target: "
            + ", ".join(drifted)
            + ". Regenerate inside the matching target environment and Python interpreter."
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify tracked pins without modifying or upgrading them",
    )
    mode.add_argument(
        "--upgrade-package",
        metavar="REQUIREMENT",
        help=(
            "upgrade only one dependency requirement while preserving the tracked pins "
            "for all three active-target graphs"
        ),
    )
    arguments = parser.parse_args(argv)

    try:
        compile_constraints(
            check=arguments.check,
            upgrade_package=arguments.upgrade_package,
        )
    except (ConstraintDriftError, UnsupportedTargetError) as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
