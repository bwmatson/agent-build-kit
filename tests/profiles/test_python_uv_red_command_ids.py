"""The python-uv red command selects tests by id when it is given ids (spec: red-check-by-id)."""

from __future__ import annotations

from typing import Any

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
