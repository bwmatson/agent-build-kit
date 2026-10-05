"""A repo that declares pytest-xdist is tested in parallel workers and then a
serial pass; a repo that does not keeps the single plain command."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.python_uv import PROFILE

PLAIN = ["uv", "run", "pytest", "-q"]
PARALLEL = ["uv", "run", "pytest", "-n", "auto", "--maxprocesses=8", "-m", "not serial", "-q"]
SERIAL = ["uv", "run", "pytest", "-m", "serial", "-q"]


def repo_with(tmp_path: Path, pyproject: str) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(pyproject)
    return tmp_path


def test_a_repo_without_xdist_keeps_the_plain_command(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, '[project]\nname = "x"\n')

    assert PROFILE.test_commands(repo, ["tests/test_x.py"], root_extras=[]) == [PLAIN]


def test_xdist_in_a_dependency_group_runs_a_parallel_then_a_serial_pass(tmp_path: Path) -> None:
    repo = repo_with(
        tmp_path,
        '[project]\nname = "x"\n[dependency-groups]\ndev = ["pytest>=8", "pytest-xdist>=3.6"]\n',
    )

    assert PROFILE.test_commands(repo, ["tests/test_x.py"], root_extras=[]) == [PARALLEL, SERIAL]
    assert PROFILE.test_commands_all(repo, root_extras=[]) == [PARALLEL, SERIAL]


def test_xdist_among_the_project_dependencies_counts(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, '[project]\nname = "x"\ndependencies = ["pytest_xdist"]\n')

    assert PROFILE.test_commands_all(repo, root_extras=[]) == [PARALLEL, SERIAL]


def test_a_dependency_that_only_starts_with_the_name_does_not_count(tmp_path: Path) -> None:
    repo = repo_with(
        tmp_path, '[project]\nname = "x"\n[dependency-groups]\ndev = ["pytest-xdist-extras"]\n'
    )

    assert PROFILE.test_commands_all(repo, root_extras=[]) == [PLAIN]


def test_the_repos_own_marker_exclusions_survive_into_both_passes(tmp_path: Path) -> None:
    """A later -m replaces the one in addopts, so the passes carry it forward."""
    repo = repo_with(
        tmp_path,
        '[dependency-groups]\ndev = ["pytest-xdist"]\n'
        "[tool.pytest.ini_options]\naddopts = \"-m 'not integration'\"\n",
    )

    parallel, serial = PROFILE.test_commands_all(repo, root_extras=[])

    assert parallel[parallel.index("-m") + 1] == "(not integration) and not serial"
    assert serial[serial.index("-m") + 1] == "(not integration) and serial"


def test_a_workspace_member_that_declares_xdist_runs_both_passes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n')
    for member, deps in (("svc-a", '"pytest-xdist"'), ("svc-b", '"pytest"')):
        (tmp_path / member / "tests").mkdir(parents=True)
        (tmp_path / member / "pyproject.toml").write_text(
            f'[project]\nname = "{member}"\n[dependency-groups]\ndev = [{deps}]\n'
        )

    commands = PROFILE.test_commands_all(tmp_path, root_extras=[])

    head = ["uv", "run", "--package", "svc-a", "--isolated", "pytest", "svc-a"]
    assert commands == [
        [*head, "-n", "auto", "--maxprocesses=8", "-m", "not serial", "-q"],
        [*head, "-m", "serial", "-q"],
        ["uv", "run", "--package", "svc-b", "--isolated", "pytest", "svc-b", "-q"],
    ]


def test_the_serial_pass_may_collect_nothing_and_no_other_command_may(tmp_path: Path) -> None:
    nothing = PROFILE.no_tests_collected_exit

    assert PROFILE.tolerates_exit(SERIAL, nothing)
    assert PROFILE.tolerates_exit(SERIAL, 0)
    assert not PROFILE.tolerates_exit(SERIAL, 1)
    assert not PROFILE.tolerates_exit(PARALLEL, nothing)
    assert not PROFILE.tolerates_exit(PLAIN, nothing)
    assert PROFILE.tolerates_exit(PLAIN, 0)


def test_tier_one_passes_when_the_serial_pass_finds_no_serial_tests(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, '[dependency-groups]\ndev = ["pytest-xdist"]\n')

    def run(command, **kwargs):
        code = PROFILE.no_tests_collected_exit if command == SERIAL else 0
        return subprocess.CompletedProcess(command, code, "", "")

    ok, _ = build_tier1(run=run, changed=lambda *a: ["tests/test_x.py"])(cwd=repo, base="main")

    assert ok
