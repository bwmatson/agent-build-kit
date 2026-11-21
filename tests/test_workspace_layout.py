import re
import tomllib
from pathlib import Path

import pytest

from tests.workspace_packages import PACKAGES, shared_init_files

ROOT = PACKAGES["root"]
CORE = "agent-build-kit-core"


CORE_PYPROJECT = PACKAGES["core"] / "pyproject.toml"


def _project(path: Path) -> dict:
    """The parsed project file, empty when there is none, so a missing file fails an assertion."""
    return tomllib.loads(path.read_text()) if path.is_file() else {}


def _dependency_names(project: dict) -> set[str]:
    return {
        re.split(r"[\[=<>~!\s;]", requirement)[0].lower().replace("_", "-")
        for requirement in project.get("project", {}).get("dependencies", [])
    }


def _ship(root: Path, *relative: str) -> None:
    for path in relative:
        target = root / "src" / "agent_build_kit" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")


def test_root_declares_the_workspace_over_packages() -> None:
    root = _project(ROOT / "pyproject.toml")

    uv = root.get("tool", {}).get("uv", {})

    assert uv.get("workspace", {}).get("members") == ["packages/*"]


def test_root_depends_on_the_core_from_the_workspace() -> None:
    root = _project(ROOT / "pyproject.toml")
    uv = root.get("tool", {}).get("uv", {})

    assert CORE in _dependency_names(root)
    assert uv.get("sources", {}).get(CORE) == dict(workspace=True)


def test_core_package_is_named_for_the_core() -> None:
    core = _project(CORE_PYPROJECT)

    assert core.get("project", {}).get("name") == CORE


def test_core_lists_no_dependency_the_root_does_not() -> None:
    root = _project(ROOT / "pyproject.toml")
    core = _project(CORE_PYPROJECT)

    assert CORE_PYPROJECT.is_file()
    assert _dependency_names(core) <= _dependency_names(root)


@pytest.mark.integration
def test_workspace_packages_share_no_init_file() -> None:
    assert shared_init_files(PACKAGES) == {}


def test_layout_check_names_a_folder_two_packages_both_give_an_init(tmp_path: Path) -> None:
    _ship(tmp_path / "a", "pipeline/__init__.py", "pipeline/one.py")
    _ship(tmp_path / "b", "pipeline/__init__.py", "pipeline/two.py")

    shared = shared_init_files({"a": tmp_path / "a", "b": tmp_path / "b"})

    assert shared == {"pipeline/__init__.py": ["a", "b"]}


@pytest.mark.parametrize("second", ["pipeline/two.py", "runtimes/__init__.py"])
def test_layout_check_passes_when_only_one_package_ships_the_init(
    tmp_path: Path, second: str
) -> None:
    _ship(tmp_path / "a", "pipeline/__init__.py")
    _ship(tmp_path / "b", second)

    assert shared_init_files({"a": tmp_path / "a", "b": tmp_path / "b"}) == {}
