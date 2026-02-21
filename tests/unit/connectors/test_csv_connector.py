from pathlib import Path

import pytest

from scalescore.connectors.csv_connector import CSVConnector
from scalescore.core.exceptions import CSVFormatError


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_load_organizations_missing_column(tmp_path: Path) -> None:
    content = "id,name\norg_1,Acme\n"
    file_path = tmp_path / "organizations.csv"
    write_file(file_path, content)

    connector = CSVConnector()
    with pytest.raises(CSVFormatError, match="Missing required columns"):
        connector.load_organizations(file_path)


def test_load_systems_parses_dependencies(tmp_path: Path) -> None:
    content = """id,org_id,name,system_type,capacity_current,capacity_max,capacity_unit,is_critical,dependencies
sys_1,org_1,CRM,crm,50,100,users,true,sys_2|sys_3
"""
    file_path = tmp_path / "systems.csv"
    write_file(file_path, content)

    connector = CSVConnector()
    systems = connector.load_systems(file_path)

    assert systems[0].dependencies == ["sys_2", "sys_3"]


def test_load_growth_signals_parses_areas(tmp_path: Path) -> None:
    content = """id,org_id,signal_type,title,target_date,magnitude,magnitude_type,confidence,affected_areas
sig_1,org_1,headcount_plan,Scale,2026-12-31,100,percentage,0.9,engineering|sales
"""
    file_path = tmp_path / "growth_signals.csv"
    write_file(file_path, content)

    connector = CSVConnector()
    signals = connector.load_growth_signals(file_path)

    assert signals[0].affected_areas[0].value == "engineering"
    assert signals[0].affected_areas[1].value == "sales"
