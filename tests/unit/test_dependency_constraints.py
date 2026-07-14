from __future__ import annotations

import importlib.util
import re
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
CONSTRAINTS = ROOT / "constraints"
COMPILER = ROOT / "scripts" / "compile_dependency_constraints.py"
SUPPORTED_MINORS = ("3.11", "3.12")
TARGETS = ("darwin-arm64", "linux-x86_64")
KINDS = ("runtime", "dev")
PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^;\s]+(?:\s*;\s*[^#\s].*)?$")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _direct_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    assert match is not None
    return _normalize(match.group())


def _pins(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _pin_names(path: Path) -> list[str]:
    return [_normalize(line.split("==", 1)[0]) for line in _pins(path)]


def _constraint_path(target: str, minor: str, kind: str) -> Path:
    return CONSTRAINTS / f"{target}-python{minor}-{kind}.txt"


def _load_compiler():
    spec = importlib.util.spec_from_file_location("dependency_constraint_compiler", COMPILER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_supported_direct_dependencies_are_constrained_in_correct_sets() -> None:
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    runtime = {_direct_name(item) for item in metadata["project"]["dependencies"]}
    dev_only = {_direct_name(item) for item in metadata["project"]["optional-dependencies"]["dev"]}

    for target in TARGETS:
        for minor in SUPPORTED_MINORS:
            runtime_names = _pin_names(_constraint_path(target, minor, "runtime"))
            dev_names = _pin_names(_constraint_path(target, minor, "dev"))

            assert all(runtime_names.count(name) == 1 for name in runtime)
            assert all(dev_names.count(name) == 1 for name in runtime | dev_only)
            assert runtime.isdisjoint(dev_only)
            assert dev_only.isdisjoint(runtime_names)


def test_every_constraint_set_includes_redis() -> None:
    for target in TARGETS:
        for minor in SUPPORTED_MINORS:
            for kind in KINDS:
                assert _pin_names(_constraint_path(target, minor, kind)).count("redis") == 1


def test_target_environment_graphs_capture_streamlit_watchdog_dependency() -> None:
    for minor in SUPPORTED_MINORS:
        for kind in KINDS:
            assert "watchdog" in _pin_names(_constraint_path("linux-x86_64", minor, kind))
            assert "watchdog" not in _pin_names(_constraint_path("darwin-arm64", minor, kind))


def test_every_constraint_entry_is_an_exact_pin_or_valid_marker_pin() -> None:
    for target in TARGETS:
        for minor in SUPPORTED_MINORS:
            for kind in KINDS:
                path = _constraint_path(target, minor, kind)
                pins = _pins(path)
                assert pins
                assert all(PIN.fullmatch(line) for line in pins), path
                assert len(_pin_names(path)) == len(set(_pin_names(path))), path


@pytest.mark.parametrize(
    ("system", "machine", "target"),
    [
        ("Darwin", "arm64", "darwin-arm64"),
        ("darwin", "aarch64", "darwin-arm64"),
        ("Linux", "x86_64", "linux-x86_64"),
        ("linux", "amd64", "linux-x86_64"),
    ],
)
def test_compiler_selects_normalized_target_environment(
    system: str,
    machine: str,
    target: str,
) -> None:
    compiler = _load_compiler()
    root = Path("/checkout")

    paths = compiler.constraint_paths(
        (3, 11),
        system=system,
        machine=machine,
        root=root,
    )

    assert paths == {
        kind: root / "constraints" / f"{target}-python3.11-{kind}.txt" for kind in KINDS
    }


def test_compiler_rejects_unsupported_python_minor() -> None:
    compiler = _load_compiler()

    with pytest.raises(compiler.UnsupportedTargetError, match="Python 3.11 or 3.12"):
        compiler.constraint_paths((3, 13), system="Linux", machine="x86_64")


@pytest.mark.parametrize(
    ("system", "machine", "message"),
    [
        ("Windows", "amd64", "unsupported target environment"),
        ("Linux", "arm64", "unsupported target environment"),
        ("Darwin", "x86_64", "unsupported target environment"),
    ],
)
def test_compiler_rejects_unsupported_target_environment(
    system: str,
    machine: str,
    message: str,
) -> None:
    compiler = _load_compiler()

    with pytest.raises(compiler.UnsupportedTargetError, match=message):
        compiler.constraint_paths((3, 12), system=system, machine=machine)


def test_check_mode_missing_constraints_does_not_create_checkout_paths(tmp_path: Path) -> None:
    compiler = _load_compiler()
    root = tmp_path / "checkout"

    with pytest.raises(compiler.ConstraintDriftError, match="missing"):
        compiler.compile_constraints(
            root=root,
            version_info=(3, 12),
            system="Linux",
            machine="x86_64",
            check=True,
            runner=lambda command: None,
        )

    assert not root.exists()


def test_check_mode_seeds_temporary_outputs_and_does_not_mutate_tracked_files(
    tmp_path: Path,
) -> None:
    compiler = _load_compiler()
    root = tmp_path / "checkout"
    constraints = root / "constraints"
    constraints.mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT.read_text(encoding="utf-8"), encoding="utf-8")
    originals: dict[Path, str] = {}
    for kind in KINDS:
        path = constraints / f"linux-x86_64-python3.12-{kind}.txt"
        content = f"accepted-{kind}==1.0\n"
        path.write_text(content, encoding="utf-8")
        originals[path] = content

    def preserving_runner(command: Sequence[str]) -> None:
        output_option = next(item for item in command if item.startswith("--output-file="))
        temporary_output = Path(output_option.split("=", 1)[1])
        expected = originals[constraints / temporary_output.name]
        assert temporary_output.read_text(encoding="utf-8") == expected

    compiler.compile_constraints(
        root=root,
        version_info=(3, 12),
        system="Linux",
        machine="amd64",
        check=True,
        runner=preserving_runner,
    )

    assert {path: path.read_text(encoding="utf-8") for path in originals} == originals


def test_ci_maps_ubuntu_jobs_to_linux_x86_64_constraints() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "constraints/linux-x86_64-python${{ matrix.python-version }}-dev.txt" in workflow
    assert "constraints/linux-x86_64-python3.12-dev.txt" in workflow
    assert "uname -m" in workflow
    assert "linux-x86_64" in workflow
    assert workflow.count("python -m pip check") >= 2
    assert "python scripts/compile_dependency_constraints.py --check" in workflow


def test_ci_preserves_check_names_and_audits_every_exact_constraint_set() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "name: Lint and Test (Python ${{ matrix.python-version }})" in workflow
    assert "name: Redis Rate Limit Integration" in workflow
    assert workflow.count("name: Dependency Security Scan") == 1
    for target in TARGETS:
        for minor in SUPPORTED_MINORS:
            for kind in KINDS:
                assert f"constraints/{target}-python{minor}-{kind}.txt" in workflow
    assert workflow.count("--strict") == 8
    assert workflow.count("--no-deps") == 8
    assert workflow.count("--disable-pip") == 8
    assert workflow.count("python -m pip_audit") == 8
    assert "scripts/run_tests.py" in workflow
