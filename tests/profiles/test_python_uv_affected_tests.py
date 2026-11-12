"""The python-uv profile's affected-tests hook (spec: affected-tests-in-fix-rounds).

With the plugin's seed data present the commands select by changed source and carry the
plugin into the isolated environment; without it they run the failed tests alone; with no
failed test to name, the profile cannot say.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.profiles.python_uv import PROFILE, reads_any_of

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


# The integration kind in the affected selection (spec: integration-tests-run-in-the-unit-gate).
DEFAULT_RUN = "not integration and not e2e and not slow"
INTEGRATION_ID = "tests/integration/test_flow.py::test_flows"


def integration_repo(tmp_path: Path) -> Path:
    """A repository whose own default run deselects the integration, e2e and slow kinds."""
    repo = plain_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "x"\n[tool.pytest.ini_options]\naddopts = "-m \'{DEFAULT_RUN}\'"\n'
    )
    return repo


def marker_of(command: list[str]) -> str:
    assert "-m" in command, command
    return command[command.index("-m") + 1]


@pytest.mark.parametrize("select", [True, False], ids=["the selection", "the recording"])
def test_the_selection_and_the_recording_let_the_integration_kind_through_the_default_run(
    tmp_path: Path, select: bool
) -> None:
    repo = integration_repo(tmp_path)
    command = ["uv", "run", "pytest", "tests"]

    seeded_run = PROFILE.seeding_command(command, tmp_path / "seed", select=select, project=repo)

    expression = marker_of(seeded_run)
    assert expression.startswith("integration or ")
    assert DEFAULT_RUN in expression


def test_the_serial_half_of_a_split_run_is_lifted_in_the_seeded_command(tmp_path: Path) -> None:
    repo = integration_repo(tmp_path)
    command = ["uv", "run", "pytest", "-m", f"({DEFAULT_RUN}) and serial", "tests"]

    seeded_run = PROFILE.seeding_command(command, tmp_path / "seed", select=True, project=repo)

    assert marker_of(seeded_run) == f"(integration or ({DEFAULT_RUN})) and serial"


def test_a_selection_that_reaches_an_integration_test_runs_it_with_a_slow_test_still_out(
    tmp_path: Path,
) -> None:
    repo = integration_repo(tmp_path)

    commands = ask(repo, ["src/x.py"], [], seeded(tmp_path))

    assert commands
    for command in commands:
        expression = marker_of(command)
        assert "integration or" in expression
        assert "not slow" in expression and "not e2e" in expression


def test_a_failed_integration_id_without_seed_data_runs_by_id_past_the_default_run(
    tmp_path: Path,
) -> None:
    repo = integration_repo(tmp_path)

    commands = ask(repo, ["src/x.py"], [INTEGRATION_ID], tmp_path / "missing" / "affected")

    assert commands and len(commands) == 1
    assert INTEGRATION_ID in commands[0]
    assert marker_of(commands[0]).startswith("integration or ")


@pytest.mark.parametrize(
    ("changed", "reads"),
    [
        ("src/a.py", True),
        ("src/pkg/deep.py", True),
        ("docs/a.md", False),
        ("src/a.md", False),
        ("pyproject.toml", True),
    ],
    ids=["under, suffix", "nested", "outside under", "other suffix", "a named root file"],
)
def test_a_scan_declaring_what_it_reads_is_selected_only_when_one_of_those_files_changes(
    changed: str, reads: bool
) -> None:
    source = (
        "from tests.tracked_files import guarded_files\n"
        "\n"
        "def test_scan():\n"
        "    guarded_files(under=['src'], names=['pyproject.toml'], suffixes={'.py', '.toml'})\n"
    )

    assert reads_any_of(source, [changed]) is reads


def test_a_scan_with_a_suffix_only_reads_those_files_across_the_whole_tree() -> None:
    source = "def test_scan():\n    guarded_files(suffixes=('.md',))\n"

    assert reads_any_of(source, ["docs/deep/a.md"])
    assert not reads_any_of(source, ["src/a.py"])


def test_a_scan_that_declares_nothing_is_affected_by_every_change() -> None:
    assert reads_any_of("def test_scan():\n    guarded_files()\n", ["src/a.py"])


def test_a_scan_whose_declaration_is_not_a_literal_is_affected_by_every_change() -> None:
    source = "FOLDERS = ['src']\n\ndef test_scan():\n    guarded_files(under=FOLDERS)\n"

    assert reads_any_of(source, ["docs/a.md"])


def test_a_module_with_two_scans_is_selected_when_either_reads_the_changed_file() -> None:
    source = (
        "def test_a():\n    guarded_files(under=['src'])\n"
        "def test_b():\n    guarded_files(under=['docs'])\n"
    )

    assert reads_any_of(source, ["docs/a.md"])
    assert not reads_any_of(source, ["web/a.ts"])


def test_a_module_that_never_calls_the_helper_reads_no_tree() -> None:
    assert not reads_any_of("def test_x():\n    assert True\n", ["src/a.py"])


def test_the_helper_is_named_by_the_caller() -> None:
    source = "def test_x():\n    walk(under=['src'])\n"

    assert reads_any_of(source, ["src/a.py"], helper="walk")
    assert not reads_any_of(source, ["docs/a.md"], helper="walk")
