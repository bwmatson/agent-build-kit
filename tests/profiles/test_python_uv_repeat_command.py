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
    assert narrowed is not None
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

    assert PythonUvProfile().repeat_command(command, ["svc-a/tests/test_a.py::test_x"]) == [
        *["uv", "run", "--package", "svc-a", "pytest"],
        *["-n", "auto", "-m", "not serial", "-q"],
        "svc-a/tests/test_a.py::test_x",
    ]


def test_a_test_of_another_member_selects_nothing() -> None:
    command = ["uv", "run", "--package", "svc-b", "--isolated", "pytest", "svc-b", "-q"]

    assert PythonUvProfile().repeat_command(command, ["svc-a/tests/test_x.py::test_y"]) is None


def test_a_member_command_keeps_only_its_own_ids() -> None:
    command = ["uv", "run", "--package", "svc-a", "--isolated", "pytest", "svc-a", "-q"]
    ids = ["svc-a/tests/test_x.py::test_y", "svc-b/tests/test_x.py::test_y", "svc-ab/t.py::t"]

    assert PythonUvProfile().repeat_command(command, ids) == [
        *["uv", "run", "--package", "svc-a", "--isolated", "pytest", "-q"],
        "svc-a/tests/test_x.py::test_y",
    ]


def test_a_command_given_no_path_keeps_every_id() -> None:
    command = ["uv", "run", "pytest", "-n", "auto"]
    ids = ["a/test_x.py::test_y", "b/test_x.py::test_z"]

    assert PythonUvProfile().repeat_command(command, ids) == [*command, *ids]


def test_a_command_run_from_a_directory_keeps_the_ids_under_it_relative_to_it() -> None:
    command = ["uv", "run", "--directory", "svc-a", "--package", "svc-a", "--isolated"]
    command += ["pytest", "-m", "local_stack", "-q"]
    ids = ["svc-a/tests/live/test_x.py::t", "svc-b/tests/live/test_y.py::u"]

    assert PythonUvProfile().repeat_command(command, ids) == [*command, "tests/live/test_x.py::t"]


def test_a_command_run_from_a_directory_selects_nothing_for_ids_outside_it() -> None:
    command = ["uv", "run", "--directory", "svc-a", "--package", "svc-a", "--isolated"]
    command += ["pytest", "-m", "local_stack", "-q"]

    assert PythonUvProfile().repeat_command(command, ["svc-b/tests/live/test_y.py::u"]) is None
