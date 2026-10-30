"""The Python profile's xdist options come from the repo's `tests.workers` and
`tests.max_workers` (spec: testmon-selection-honours-markers)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.profiles import python_uv

PROFILE = python_uv.PROFILE

XDIST_PROJECT = '[project]\nname = "x"\n[dependency-groups]\ndev = ["pytest-xdist"]\n'
PLAIN_PROJECT = '[project]\nname = "x"\n'
WORKSPACE = '[tool.uv.workspace]\nmembers = ["svc-a"]\n'


def contains(command: list[str], words: list[str]) -> bool:
    return any(command[i : i + len(words)] == words for i in range(len(command)))


def whole_repo(tmp_path: Path, pyproject: str) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(pyproject)
    return tmp_path


def workspace(tmp_path: Path, member_pyproject: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(WORKSPACE)
    (tmp_path / "svc-a" / "tests").mkdir(parents=True)
    (tmp_path / "svc-a" / "pyproject.toml").write_text(member_pyproject)
    return tmp_path


def test_the_defaults_are_the_options_the_full_run_has_always_had(tmp_path: Path) -> None:
    repo = whole_repo(tmp_path, XDIST_PROJECT)

    parallel, serial = PROFILE.test_commands_all(
        repo, root_extras=[], workers="auto", max_workers=8
    )

    assert contains(parallel, ["-n", "auto", "--maxprocesses=8", "-m"])
    assert "-n" not in serial


def test_the_settings_replace_the_workers_of_both_full_run_commands(tmp_path: Path) -> None:
    repo = whole_repo(tmp_path, XDIST_PROJECT)

    for commands in (
        PROFILE.test_commands(repo, ["tests/t.py"], root_extras=[], workers=4, max_workers=6),
        PROFILE.test_commands_all(repo, root_extras=[], workers=4, max_workers=6),
    ):
        parallel, serial = commands
        assert contains(parallel, ["-n", "4", "--maxprocesses=6"])
        assert "auto" not in parallel
        assert "--maxprocesses=8" not in parallel
        assert "-n" not in serial


def test_a_workspace_members_parallel_pass_carries_them(tmp_path: Path) -> None:
    repo = workspace(tmp_path, XDIST_PROJECT.replace('"x"', '"svc-a"'))

    parallel, _serial = PROFILE.test_commands_all(repo, root_extras=[], workers=4, max_workers=6)

    assert contains(parallel, ["-n", "4", "--maxprocesses=6"])


def test_the_root_tests_of_a_workspace_carry_them_when_xdist_is_an_extra(tmp_path: Path) -> None:
    repo = workspace(tmp_path, PLAIN_PROJECT.replace('"x"', '"svc-a"'))
    (repo / "tests").mkdir()

    *_, root_parallel, _root_serial = PROFILE.test_commands_all(
        repo, root_extras=["pytest-xdist"], workers=4, max_workers=6
    )

    assert contains(root_parallel, ["-n", "4", "--maxprocesses=6"])


def test_a_repo_without_xdist_gets_no_workers_option(tmp_path: Path) -> None:
    repo = whole_repo(tmp_path, PLAIN_PROJECT)

    (command,) = PROFILE.test_commands_all(repo, root_extras=[], workers=4, max_workers=6)

    assert "-n" not in command
    assert not any(word.startswith("--maxprocesses") for word in command)


def test_the_selection_commands_of_a_seeded_run_carry_them_too(tmp_path: Path) -> None:
    repo = whole_repo(tmp_path, XDIST_PROJECT)
    seed = tmp_path / "seed.db"
    seed.write_text("")

    selected = PROFILE.affected_test_commands(
        repo, ["src/x.py"], [], seed=seed, root_extras=[], workers=4, max_workers=6
    )

    assert selected is not None
    assert contains(selected[0], ["-n", "4", "--maxprocesses=6"])
