"""A repo that declares pytest-xdist is tested in parallel workers, in one pass; a repo that does
not keeps the single plain command."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.profiles.python_uv import PROFILE, UNIT_REPORT_FLAGS
from tests.serial_marker import MARKER

REPORT = UNIT_REPORT_FLAGS
PLAIN = ["uv", "run", "pytest", "-q", *REPORT]
PARALLEL = [*["uv", "run", "pytest", "-n", "auto", "--maxprocesses=8", "-v"], *REPORT]


def repo_with(tmp_path: Path, pyproject: str) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(pyproject)
    return tmp_path


def test_a_repo_without_xdist_keeps_the_plain_command(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, '[project]\nname = "x"\n')

    assert PROFILE.test_commands(repo, ["tests/test_x.py"], root_extras=[]) == [PLAIN]


def test_xdist_in_a_dependency_group_runs_one_parallel_pass(tmp_path: Path) -> None:
    repo = repo_with(
        tmp_path,
        '[project]\nname = "x"\n[dependency-groups]\ndev = ["pytest>=8", "pytest-xdist>=3.6"]\n',
    )

    assert PROFILE.test_commands(repo, ["tests/test_x.py"], root_extras=[]) == [PARALLEL]
    assert PROFILE.test_commands_all(repo, root_extras=[]) == [PARALLEL]


def test_the_parallel_pass_runs_at_verbosity_one_or_more_also_when_selected(
    tmp_path: Path,
) -> None:
    """xdist prints each worker's progress lines only from `-v`; the consequence reader needs
    them, so a testmon selection (which nets `-q` back to the default) must not lose them."""
    repo = repo_with(tmp_path, '[dependency-groups]\ndev = ["pytest-xdist"]\n')
    commands = PROFILE.test_commands_all(repo, root_extras=[])
    assert len(commands) == 1, commands
    parallel = commands[0]

    selected = PROFILE.seeding_command(parallel, tmp_path / "seed", select=True)

    for command in (parallel, selected):
        assert command.count("-v") - command.count("-q") >= 1


def test_xdist_among_the_project_dependencies_counts(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, '[project]\nname = "x"\ndependencies = ["pytest_xdist"]\n')

    assert PROFILE.test_commands_all(repo, root_extras=[]) == [PARALLEL]


def test_a_dependency_that_only_starts_with_the_name_does_not_count(tmp_path: Path) -> None:
    repo = repo_with(
        tmp_path, '[project]\nname = "x"\n[dependency-groups]\ndev = ["pytest-xdist-extras"]\n'
    )

    assert PROFILE.test_commands_all(repo, root_extras=[]) == [PLAIN]


def test_the_one_pass_adds_no_marker_selection_so_the_repos_addopts_stand(
    tmp_path: Path,
) -> None:
    repo = repo_with(
        tmp_path,
        '[dependency-groups]\ndev = ["pytest-xdist"]\n'
        "[tool.pytest.ini_options]\naddopts = \"-m 'not integration'\"\n",
    )

    assert PROFILE.test_commands_all(repo, root_extras=[]) == [PARALLEL]


def test_a_workspace_member_that_declares_xdist_runs_one_pass(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n')
    for member, deps in (("svc-a", '"pytest-xdist"'), ("svc-b", '"pytest"')):
        (tmp_path / member / "tests").mkdir(parents=True)
        (tmp_path / member / "pyproject.toml").write_text(
            f'[project]\nname = "{member}"\n[dependency-groups]\ndev = [{deps}]\n'
        )

    commands = PROFILE.test_commands_all(tmp_path, root_extras=[])

    head = ["uv", "run", "--package", "svc-a", "--isolated", "pytest", "svc-a"]
    assert commands == [
        [*head, "-n", "auto", "--maxprocesses=8", "-v", *REPORT],
        ["uv", "run", "--package", "svc-b", "--isolated", "pytest", "svc-b", "-q", *REPORT],
    ]


def test_no_command_tolerates_an_exit_for_collecting_nothing_not_even_a_marker_selection() -> None:
    nothing = PROFILE.no_tests_collected_exit
    selected = ["uv", "run", "pytest", "-m", MARKER, "-q", *REPORT]

    assert not PROFILE.tolerates_exit(selected, nothing)
    assert not PROFILE.tolerates_exit(PARALLEL, nothing)
    assert not PROFILE.tolerates_exit(PLAIN, nothing)
    assert PROFILE.tolerates_exit(PLAIN, 0)
