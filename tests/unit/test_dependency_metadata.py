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


def test_frontend_dependencies_are_separate_from_the_core_graph() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text())
    core = {
        requirement.split(">=", 1)[0].lower()
        for requirement in pyproject["project"]["dependencies"]
    }
    optional_dependencies = pyproject["project"]["optional-dependencies"]
    frontend_requirements = optional_dependencies["frontend"]
    frontend = {requirement.split(">=", 1)[0].lower() for requirement in frontend_requirements}

    assert frontend == {"plotly", "protobuf", "requests", "streamlit"}
    assert core.isdisjoint(frontend)
    assert {"cryptography", "pandas", "pillow", "reportlab"} <= core
    assert "pillow>=12.1.1" in pyproject["project"]["dependencies"]
    assert "protobuf>=6.33.5" in frontend_requirements
    assert "ml" not in optional_dependencies
