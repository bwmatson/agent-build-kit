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
ROOT_ID = "tests/test_root.py::test_z"


def ask(
    repo: Path,
    changed: list[str],
    ids: list[str],
    seed: Path,
    root_extras: list[str] | None = None,
) -> list[list[str]] | None:
    return PROFILE.affected_test_commands(
        repo, changed, ids, seed=seed, root_extras=root_extras or []
    )


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
    seed = tmp_path / "seed" / "affected"
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

    commands = ask(repo, ["svc-a/src/x.py"], [ID_A], seed)

    assert commands
    for command in commands:
        assert "--isolated" in command
        assert command[command.index("--with") + 1].startswith("pytest-testmon")
        assert "--testmon-forceselect" in command and "--testmon" not in command
        assert any(str(seed) in word for word in command)
        assert command[command.index("--package") + 1] == "svc-a"
    assert "svc-b" not in " ".join(words(commands))


def test_seed_data_in_a_repo_that_is_not_a_workspace_selects_by_changed_source(
    tmp_path: Path,
) -> None:
    repo = plain_repo(tmp_path)

    commands = ask(repo, ["src/x.py"], [], seeded(tmp_path))

    assert "--testmon-forceselect" in words(commands)
    assert "--testmon" not in words(commands)


def test_without_seed_data_the_failed_tests_run_first_and_alone(tmp_path: Path) -> None:
    repo = workspace_repo(tmp_path)

    commands = ask(repo, ["svc-a/src/x.py"], [ID_A], tmp_path / "missing" / "affected")

    assert commands
    for command in commands:
        assert "pytest" in command and ID_A in command
        assert command[command.index("--package") + 1] == "svc-a"
        assert not any("testmon" in word for word in command)
        # The test run is the named one, not the member's whole directory.
        assert "svc-a" not in command[command.index("pytest") + 1 :]
    assert "svc-b" not in " ".join(words(commands))


def test_without_seed_data_a_repo_that_is_not_a_workspace_runs_the_failed_test_alone(
    tmp_path: Path,
) -> None:
    repo = plain_repo(tmp_path)

    commands = ask(repo, ["src/x.py"], [PLAIN_ID], tmp_path / "affected")

    assert commands and len(commands) == 1
    assert commands[0].count(PLAIN_ID) == 1
    assert "tests" not in commands[0]


def test_with_no_identifiers_and_no_seed_data_it_cannot_say(tmp_path: Path) -> None:
    repo = plain_repo(tmp_path)

    assert ask(repo, ["src/x.py"], [], tmp_path / "affected") is None


def test_the_root_tests_carry_the_repos_root_extras_seeded_and_not(tmp_path: Path) -> None:
    repo = workspace_repo(tmp_path)
    (repo / "tests").mkdir()

    for seed in (seeded(tmp_path), tmp_path / "missing" / "affected"):
        commands = ask(repo, ["tests/test_root.py"], [ROOT_ID], seed, ["httpx"])

        assert commands
        root = [c for c in commands if "--package" not in c]
        assert root, commands
        for command in root:
            withs = [command[i + 1] for i, word in enumerate(command) if word == "--with"]
            assert "httpx" in withs


def test_the_select_form_forces_the_selection_between_the_plugin_and_the_paths() -> None:
    command = ["uv", "run", "pytest", "-m", "not slow", "tests"]

    selected = PROFILE.seeding_command(command, Path("/seed"), select=True)

    assert "--testmon" not in selected and "--testmon-noselect" not in selected
    assert selected.index("--with") < selected.index("--testmon-forceselect")
    assert selected.index("--testmon-forceselect") < selected.index("-m")
    assert selected[selected.index("-m") + 1] == "not slow"
    assert selected[-1] == "tests"


def test_the_recording_form_still_runs_every_test() -> None:
    command = ["uv", "run", "pytest", "-m", "not slow", "tests"]

    recording = PROFILE.seeding_command(command, Path("/seed"))

    assert "--testmon-noselect" in recording
    assert "--testmon-forceselect" not in recording and "--testmon" not in recording
    assert recording[recording.index("-m") + 1] == "not slow"
