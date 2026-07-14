from __future__ import annotations

import os
import sys
from pathlib import Path

PROVENANCE_ERROR = 2


def _imported_package_path() -> tuple[Path | None, str]:
    try:
        import scalescore
    except Exception as error:  # noqa: BLE001 - any package import failure must fail closed
        return None, f"unavailable ({type(error).__name__})"

    module_file = getattr(scalescore, "__file__", None)
    if not isinstance(module_file, str):
        return None, "unavailable (scalescore.__file__ is missing)"

    try:
        imported_path = Path(module_file).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        return None, f"unavailable ({type(error).__name__})"
    return imported_path, str(imported_path)


def _report_provenance_failure(
    *,
    repo_root: Path,
    logical_source: Path,
    resolved_source: str,
    imported_path: str,
) -> None:
    print("Checkout provenance check failed.", file=sys.stderr)
    print(f"Interpreter: {Path(sys.executable).resolve()}", file=sys.stderr)
    print(f"Checkout source (logical): {logical_source}", file=sys.stderr)
    print(f"Checkout source (resolved): {resolved_source}", file=sys.stderr)
    print(f"Imported scalescore: {imported_path}", file=sys.stderr)
    print(
        "Deactivate the current environment, remove only this checkout's .venv, then rebuild it:",
        file=sys.stderr,
    )
    print(
        "Use Python 3.11 or newer; CI covers Python 3.11 and 3.12.",
        file=sys.stderr,
    )
    print(f"  cd {repo_root}", file=sys.stderr)
    print("  python -m venv .venv", file=sys.stderr)
    venv_python = r".venv\Scripts\python.exe" if os.name == "nt" else ".venv/bin/python"
    print(f'  {venv_python} -m pip install -e ".[dev]"', file=sys.stderr)


def _has_expected_provenance(repo_root: Path) -> bool:
    logical_source = repo_root / "src" / "scalescore"
    try:
        resolved_source = logical_source.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        _report_provenance_failure(
            repo_root=repo_root,
            logical_source=logical_source,
            resolved_source=f"unavailable ({type(error).__name__})",
            imported_path="not checked (checkout source is invalid)",
        )
        return False

    if resolved_source != logical_source or not resolved_source.is_relative_to(repo_root):
        _report_provenance_failure(
            repo_root=repo_root,
            logical_source=logical_source,
            resolved_source=str(resolved_source),
            imported_path="not checked (checkout source is invalid)",
        )
        return False

    imported_path, imported_description = _imported_package_path()
    if imported_path is not None and imported_path.is_relative_to(resolved_source):
        return True

    _report_provenance_failure(
        repo_root=repo_root,
        logical_source=logical_source,
        resolved_source=str(resolved_source),
        imported_path=imported_description,
    )
    return False


def main() -> int:
    """Validate checkout provenance, then delegate arguments to pytest."""
    repo_root = Path(__file__).resolve().parents[1]
    if not _has_expected_provenance(repo_root):
        return PROVENANCE_ERROR

    import pytest

    return pytest.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
