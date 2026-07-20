#!/usr/bin/env python3
"""Require exact bidirectional Python package/version parity between inventory and SBOM."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote

PackageVersion = tuple[str, str]


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _unique_package_versions(
    values: Iterable[PackageVersion], *, source: str
) -> set[PackageVersion]:
    result: set[PackageVersion] = set()
    names: set[str] = set()
    for name, version in values:
        normalized = _normalize_name(name)
        item = (normalized, version)
        if normalized in names or item in result:
            raise ValueError(f"duplicate Python package in {source}: {normalized}")
        names.add(normalized)
        result.add(item)
    return result


def _inventory_packages(document: Any) -> set[PackageVersion]:
    if not isinstance(document, list):
        raise ValueError("runtime inventory must be a JSON list")
    values: list[PackageVersion] = []
    for item in document:
        if not isinstance(item, dict):
            raise ValueError("runtime inventory entries must be JSON objects")
        name = item.get("name")
        version = item.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("runtime inventory entries require string name and version")
        values.append((name, version))
    return _unique_package_versions(values, source="runtime inventory")


def _sbom_packages(document: Any) -> set[PackageVersion]:
    if not isinstance(document, dict) or not isinstance(document.get("components"), list):
        raise ValueError("CycloneDX SBOM must contain a components list")
    values: list[PackageVersion] = []
    for component in document["components"]:
        if not isinstance(component, dict):
            continue
        purl = component.get("purl")
        if not isinstance(purl, str) or not purl.startswith("pkg:pypi/"):
            continue
        name = unquote(purl.removeprefix("pkg:pypi/").split("@", 1)[0])
        version = component.get("version")
        if not name or not isinstance(version, str) or not version:
            raise ValueError(f"Python SBOM component lacks name/version: {purl}")
        values.append((name, version))
    return _unique_package_versions(values, source="CycloneDX SBOM")


def verify_parity(
    inventory_path: Path, sbom_path: Path
) -> tuple[set[PackageVersion], set[PackageVersion]]:
    """Return package/version pairs present on only one side of the artifact evidence."""
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    inventory_packages = _inventory_packages(inventory)
    sbom_packages = _sbom_packages(sbom)
    return inventory_packages - sbom_packages, sbom_packages - inventory_packages


def _format(items: set[PackageVersion]) -> str:
    return ", ".join(f"{name}=={version}" for name, version in sorted(items)) or "none"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("sbom", type=Path)
    arguments = parser.parse_args(argv)
    try:
        inventory_only, sbom_only = verify_parity(arguments.inventory, arguments.sbom)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"error: {error}\n")
    if inventory_only or sbom_only:
        parser.exit(
            1,
            "error: runtime inventory and CycloneDX SBOM differ\n"
            f"inventory only: {_format(inventory_only)}\n"
            f"SBOM only: {_format(sbom_only)}\n",
        )
    print("runtime inventory and CycloneDX SBOM have exact Python package/version parity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
