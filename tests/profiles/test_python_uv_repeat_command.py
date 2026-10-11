"""The python-uv profile's repeat command, run through real pytest on a fixture tree
(spec: flaky-tests): exactly the touched tests are collected, and no others."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent_build_kit.profiles.python_uv import PythonUvProfile

TREE = {
    "tests/test_a.py": (
        "def test_added():\n    pass\n\n\n"
        "def test_added_twice():\n    pass\n\n\n"
        "class TestGroup:\n    def test_added(self):\n        pass\n"
    ),
    "tests/test_added.py": "def test_other():\n    pass\n",
}


def collected(tmp_path: Path, ids: list[str], command: list[str]) -> set[str]:
    for name, text in TREE.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    narrowed = PythonUvProfile().repeat_command(command, ids)
    result = subprocess.run(
        [*narrowed, "--collect-only", "-p", "no:cacheprovider"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {line for line in result.stdout.splitlines() if "::" in line}


def test_only_the_named_test_is_collected_not_its_namesakes_or_a_module_of_that_name(
    tmp_path: Path,
) -> None:
    command = [sys.executable, "-m", "pytest", "tests", "-m", "not serial", "-q"]

    found = collected(tmp_path, ["tests/test_a.py::test_added"], command)

    assert found == {"tests/test_a.py::test_added"}


def test_a_method_is_collected_by_its_class_path_alone(tmp_path: Path) -> None:
    command = [sys.executable, "-m", "pytest", "tests", "-q"]

    found = collected(tmp_path, ["tests/test_a.py::TestGroup::test_added"], command)

    assert found == {"tests/test_a.py::TestGroup::test_added"}


def test_the_options_of_the_run_stay_and_its_paths_go() -> None:
    command = ["uv", "run", "--package", "svc-a", "pytest", "svc-a"]
    command += ["-n", "auto", "-m", "not serial", "-q"]

    assert PythonUvProfile().repeat_command(command, ["tests/test_a.py::test_x"]) == [
        *["uv", "run", "--package", "svc-a", "pytest"],
        *["-n", "auto", "-m", "not serial", "-q"],
        "tests/test_a.py::test_x",
    ]
