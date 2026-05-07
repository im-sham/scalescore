from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"


def test_opsorchestra_extra_does_not_resolve_public_package_name() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text())

    optional_dependencies = pyproject["project"]["optional-dependencies"]
    assert optional_dependencies["opsorchestra"] == []
    assert "opsorchestra>=0.1.0" not in PYPROJECT.read_text()
