"""The python-uv red command selects tests by id when it is given ids (spec: red-check-by-id)."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.factories import init_repo

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


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A uv workspace root listing `pkg/core` and the nested `apps/functions` as members, with
    `pkg/other` a folder it does not list."""
    root = init_repo(tmp_path / "ws")
    (root / "uv.lock").write_text("version = 1\n")
    for folder in ("pkg/core", "apps/functions", "pkg/other"):
        (root / folder).mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "root"\nversion = "0"\n'
        '[tool.uv.workspace]\nmembers = ["pkg/core", "apps/functions"]\n'
    )
    return root


@pytest.fixture
def plain(tmp_path: Path) -> Path:
    """A project folder in a repository that declares no workspace."""
    root = init_repo(tmp_path / "plain")
    (root / "pkg/core").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "root"\nversion = "0"\n')
    return root


@pytest.mark.parametrize("member", ["pkg/core", "apps/functions"])
def test_a_workspace_members_red_command_runs_in_the_workspace_environment_on_the_lock_as_is(
    workspace: Path, plain: Path, member: str
) -> None:
    profile: Any = PythonUvProfile()

    command = profile.red_command(FILES, project=workspace / member)

    words = shlex.split(command)
    assert "--all-packages" in words
    assert "--frozen" in words
    assert command != profile.red_command(FILES, project=plain / "pkg/core")


def test_a_member_of_a_workspace_with_no_lock_keeps_the_command_built_today(
    workspace: Path, plain: Path
) -> None:
    profile: Any = PythonUvProfile()
    (workspace / "uv.lock").unlink()

    command = profile.red_command(FILES, project=workspace / "pkg/core")

    assert command == profile.red_command(FILES, project=plain / "pkg/core")
    assert "--frozen" not in shlex.split(command)


@pytest.mark.parametrize("ids", [None, IDS])
def test_a_project_that_is_not_a_member_keeps_the_command_built_today(
    workspace: Path, plain: Path, ids: list[str] | None
) -> None:
    profile: Any = PythonUvProfile()
    today = profile.red_command(FILES, ids, project=plain / "pkg/core")

    assert profile.red_command(FILES, ids, project=workspace) == today, "the root's own project"
    assert profile.red_command(FILES, ids, project=workspace / "pkg/other") == today
    assert profile.red_command(FILES, ids, project=plain) == today
    assert "--all-packages" not in shlex.split(today)
    assert profile.red_command(FILES, ids, project=workspace / "pkg/core") != today, "a member"


def test_a_members_red_command_still_selects_by_id_retries_the_file_whole_and_prints_the_report(
    workspace: Path,
) -> None:
    profile: Any = PythonUvProfile()

    command = profile.red_command(FILES, IDS, project=workspace / "pkg/core")

    first, _, after = command.partition('if [ "$status" -eq 4 ]; then ')
    assert "tests/test_a.py::test_new" in first
    assert "tests/test_b.py" not in first
    assert "tests/test_a.py tests/test_b.py" in after, "the retry runs the files whole"
    assert "--all-packages" in after, "and in the workspace environment too"
    assert "--junitxml" in command


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
    lost = ["params.py::test_y[e f]", "params.py::test_y[g h]"]
    kept = ["params.py::test_y[a b]"]

    ran = pytester.runpytest_subprocess(*lost[:1])
    output = f"{ran.stdout.str()}\n{ran.stderr.str()}"

    assert ran.ret == PythonUvProfile().usage_error_exit
    profile = PythonUvProfile()
    assert profile.ids_not_found(output, pytester.path) == ["params.py::test_y"]
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
