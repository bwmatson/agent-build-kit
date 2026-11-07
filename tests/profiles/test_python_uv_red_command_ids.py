"""The python-uv red command selects tests by id when it is given ids (spec: red-check-by-id)."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.profiles.python_uv import PythonUvProfile

FILES = ["tests/test_a.py", "tests/test_b.py"]
IDS = ["tests/test_a.py::test_new", "tests/test_a.py::TestGroup::test_changed"]


def test_ids_are_passed_as_path_and_name_arguments_in_place_of_the_files() -> None:
    profile: Any = PythonUvProfile()

    command = profile.red_command(FILES, IDS)

    first, _, after = command.partition('if [ "$status" -eq 4 ]; then ')
    assert "pytest tests/test_a.py::test_new tests/test_a.py::TestGroup::test_changed " in first
    assert "tests/test_b.py" not in first
    assert "-p no:cacheprovider --tb=line -q" in first
    # On pytest's usage error (an id it did not collect) the files run whole in its place.
    assert after.startswith("uv run pytest tests/test_a.py tests/test_b.py -p no:cacheprovider")


def test_without_ids_the_command_is_the_whole_file_run_and_with_them_it_is_not() -> None:
    profile: Any = PythonUvProfile()

    whole = profile.red_command(FILES, None)

    assert "pytest tests/test_a.py tests/test_b.py -p no:cacheprovider --tb=line -q" in whole
    assert profile.red_command(FILES, []) == whole
    assert profile.red_command(FILES) == whole
    assert profile.red_command(FILES, IDS) != whole


SPACED = "tests/a/test_x.py::test_y[no conversation found with session id sess-1]"


def test_the_by_id_red_command_passes_an_id_with_spaces_and_brackets_as_one_argument() -> None:
    profile: Any = PythonUvProfile()

    command = profile.red_command(["tests/a/test_x.py"], [SPACED])

    first, _, after = command.partition('if [ "$status" -eq 4 ]; then ')
    assert shlex.quote(SPACED) in first
    assert shlex.quote(SPACED) not in after, "the retry runs the files whole"
    assert after.startswith("uv run pytest tests/a/test_x.py -p no:cacheprovider")


def test_the_ids_a_real_pytest_cannot_find_are_every_parametrization_of_the_reported_function(
    pytester: pytest.Pytester,
) -> None:
    pytester.copy_example("ids_not_found")
    lost = ["test_x.py::test_y[e f]", "test_x.py::test_y[g h]"]
    kept = ["test_x.py::test_y[a b]"]

    ran = pytester.runpytest_subprocess(*lost[:1])
    output = f"{ran.stdout.str()}\n{ran.stderr.str()}"

    assert ran.ret == PythonUvProfile().usage_error_exit
    profile = PythonUvProfile()
    assert profile.ids_not_found(output, pytester.path) == ["test_x.py::test_y"]
    assert profile.ids_not_found(output, pytester.path, [*lost, *kept]) == [*lost, *kept]


def test_a_reported_path_is_made_relative_through_a_symlinked_working_directory(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    output = f"ERROR: not found: {real / 'tests' / 'test_x.py'}::test_y\n(no match in any of [])\n"

    found = PythonUvProfile().ids_not_found(output, link, ["tests/test_x.py::test_y[a b]"])

    assert found == ["tests/test_x.py::test_y[a b]"]
