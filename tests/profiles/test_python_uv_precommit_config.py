"""python-uv finds the pre-commit configuration above the folder a check runs in
(spec: shared-quality-gate).

Fixture folder trees in `tmp_path`; the git root is the folder named `root`. Nothing runs
pre-commit: the commands are only read.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from agent_build_kit.profiles.python_uv import PROFILE

CONFIG = ".pre-commit-config.yaml"


def tree(tmp_path: Path, *configs: str) -> tuple[Path, Path]:
    """A git root holding `project/`, with a configuration at each of `configs` (folders
    relative to the root; `.` is the root itself). Returns (root, project folder)."""
    root = tmp_path / "root"
    project = root / "project"
    (project / "pkg").mkdir(parents=True)
    for folder in configs:
        (root / folder / CONFIG).write_text("repos: []\n")
    return root, project


def checks(where: Path, root: Path) -> dict[str, list[str]]:
    """The five commands of the profile as an argv each, built for a run in `where`. The
    clean command is a shell line, as the pipeline runs it, so it is the argv of `sh -c`."""
    return {
        "diff": PROFILE.with_check_config(PROFILE.lint_command("main"), where, root),
        "all": PROFILE.with_check_config(PROFILE.lint_command_all_files(), where, root),
        "clean": PROFILE.with_check_config(
            ["sh", "-c", PROFILE.clean_command(types=True)], where, root
        ),
        "clean-no-types": PROFILE.with_check_config(
            ["sh", "-c", PROFILE.clean_command()], where, root
        ),
        "fix": PROFILE.with_check_config(PROFILE.fix_command(["a.py", "b.py"]) or [], where, root),
    }


def words(argv: list[str]) -> list[str]:
    """The words of a command, reading a `sh -c` line as the words it holds."""
    return shlex.split(argv[-1]) if argv[:2] == ["sh", "-c"] else argv


def config_of(argv: list[str]) -> str | None:
    """The file `--config` names, or None when the command has no such argument."""
    found = words(argv)
    return found[found.index("--config") + 1] if "--config" in found else None


def without_config(argv: list[str]) -> list[str]:
    found = words(argv)
    if "--config" not in found:
        return found
    at = found.index("--config")
    return found[:at] + found[at + 2 :]


def test_a_configuration_at_the_root_is_passed_relative_to_the_project_folder(
    tmp_path: Path,
) -> None:
    root, project = tree(tmp_path, ".")

    command = PROFILE.with_check_config(PROFILE.lint_command("main"), project, root)

    assert config_of(command) == f"../{CONFIG}"
    assert without_config(command) == PROFILE.lint_command("main")


def test_the_project_own_configuration_wins(tmp_path: Path) -> None:
    root, project = tree(tmp_path, ".", "project")

    command = PROFILE.with_check_config(PROFILE.lint_command("main"), project, root)

    assert config_of(command) == CONFIG


def test_the_nearest_configuration_above_is_used(tmp_path: Path) -> None:
    root, project = tree(tmp_path, ".", "project")
    (project / CONFIG).unlink()
    (project / "pkg" / "inner").mkdir()
    (project / "pkg" / CONFIG).write_text("repos: []\n")

    command = PROFILE.with_check_config(
        PROFILE.lint_command("main"), project / "pkg" / "inner", root
    )

    assert config_of(command) == f"../{CONFIG}"


def test_the_repo_root_finds_its_own_configuration(tmp_path: Path) -> None:
    root, _ = tree(tmp_path, ".")

    command = PROFILE.with_check_config(PROFILE.lint_command("main"), root, root)

    assert config_of(command) == CONFIG


def test_all_four_commands_carry_the_same_configuration(tmp_path: Path) -> None:
    root, project = tree(tmp_path, ".")

    built = checks(project, root)

    assert {name: config_of(argv) for name, argv in built.items()} == dict.fromkeys(
        built, f"../{CONFIG}"
    )
    assert "SKIP=pyrefly-check" in words(built["clean-no-types"])
    assert "SKIP=pyrefly-check" not in words(built["clean"])
    assert built["fix"][-2:] == ["a.py", "b.py"]


def test_no_configuration_anywhere_leaves_every_command_as_it_is(tmp_path: Path) -> None:
    root, project = tree(tmp_path)

    built = checks(project, root)

    assert built["diff"] == PROFILE.lint_command("main")
    assert built["all"] == PROFILE.lint_command_all_files()
    assert built["clean"] == ["sh", "-c", PROFILE.clean_command(types=True)]
    assert built["clean-no-types"] == ["sh", "-c", PROFILE.clean_command()]
    assert built["fix"] == PROFILE.fix_command(["a.py", "b.py"])


@pytest.mark.parametrize("where", ["project", "."])
def test_a_configuration_above_the_git_root_is_ignored(tmp_path: Path, where: str) -> None:
    root, project = tree(tmp_path)
    (tmp_path / CONFIG).write_text("repos: []\n")

    built = checks(project if where == "project" else root, root)

    assert {name: config_of(argv) for name, argv in built.items()} == dict.fromkeys(built)
