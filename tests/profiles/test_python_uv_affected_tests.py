"""The python-uv profile's affected-tests hook (spec: affected-tests-in-fix-rounds).

With the plugin's seed data present the commands select by changed source and carry the
plugin into the isolated environment; without it they run the failed tests alone; with no
failed test to name, the profile cannot say.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.profiles.python_uv import PROFILE

ID_A = "svc-a/tests/test_x.py::test_y"
PLAIN_ID = "tests/test_x.py::test_y"


def plain_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "plain"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
    return repo


def workspace_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "workspace"
    for member in ("svc-a", "svc-b"):
        (repo / member / "tests").mkdir(parents=True)
        (repo / member / "pyproject.toml").write_text(f'[project]\nname = "{member}"\n')
    (repo / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n')
    return repo


def seeded(tmp_path: Path) -> Path:
    seed = tmp_path / "seed" / ".abk-affected"
    seed.parent.mkdir()
    seed.write_bytes(b"recorded by the first full run")
    return seed


def words(commands: list[list[str]] | None) -> list[str]:
    assert commands
    return [word for command in commands for word in command]


def test_seed_data_selects_by_changed_source_with_the_plugin_in_the_isolated_environment(
    tmp_path: Path,
) -> None:
    repo = workspace_repo(tmp_path)
    seed = seeded(tmp_path)

    commands = PROFILE.affected_test_commands(repo, ["svc-a/src/x.py"], [ID_A], seed=seed)

    assert commands
    for command in commands:
        assert "--isolated" in command
        assert command[command.index("--with") + 1].startswith("pytest-testmon")
        assert "--testmon" in command
        assert any(str(seed) in word for word in command)
        assert command[command.index("--package") + 1] == "svc-a"
    assert "svc-b" not in " ".join(words(commands))


def test_seed_data_in_a_repo_that_is_not_a_workspace_selects_by_changed_source(
    tmp_path: Path,
) -> None:
    repo = plain_repo(tmp_path)

    commands = PROFILE.affected_test_commands(repo, ["src/x.py"], [], seed=seeded(tmp_path))

    assert "--testmon" in words(commands)


def test_without_seed_data_the_failed_tests_run_first_and_alone(tmp_path: Path) -> None:
    repo = workspace_repo(tmp_path)

    commands = PROFILE.affected_test_commands(
        repo, ["svc-a/src/x.py"], [ID_A], seed=tmp_path / "missing" / ".abk-affected"
    )

    assert commands
    for command in commands:
        assert "pytest" in command and ID_A in command
        assert command[command.index("--package") + 1] == "svc-a"
        assert not any("testmon" in word for word in command)
    # The test run is the named one, not the member's whole directory.
    assert "svc-a" not in words(commands)
    assert "svc-b" not in " ".join(words(commands))


def test_without_seed_data_a_repo_that_is_not_a_workspace_runs_the_failed_test_alone(
    tmp_path: Path,
) -> None:
    repo = plain_repo(tmp_path)

    commands = PROFILE.affected_test_commands(
        repo, ["src/x.py"], [PLAIN_ID], seed=tmp_path / ".abk-affected"
    )

    assert commands and len(commands) == 1
    assert commands[0].count(PLAIN_ID) == 1
    assert "tests" not in commands[0]


def test_with_no_identifiers_and_no_seed_data_it_cannot_say(tmp_path: Path) -> None:
    repo = plain_repo(tmp_path)

    commands = PROFILE.affected_test_commands(repo, ["src/x.py"], [], seed=tmp_path / ".abk")

    assert commands is None
