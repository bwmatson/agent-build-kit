"""The scratch app a build test creates tells its build agent how to run the tests and the
linter, in the commands the toolchain profile allows.

The headless build session can run only what the profile's `allowed_tools` permits, so an agent
that guesses a bare `pytest` or `ruff` cannot run its tests and writes the implementation first.
"""

from __future__ import annotations

import re
import shlex
from fnmatch import fnmatchcase
from pathlib import Path

from agent_build_kit import profiles
from tests.factories import git, scratch_app

PROFILE = profiles.get("python-uv")
BARE = re.compile(r"(?<![\w-])(?:python -m pytest|pytest|ruff)\b")


def allowed(command: list[str]) -> bool:
    """Whether the profile's `allowed_tools` has a `Bash(<pattern>)` entry matching `command`."""
    patterns = re.findall(r"Bash\((.*?)\)", PROFILE.allowed_tools)
    line = shlex.join(command)
    return any(fnmatchcase(line, pattern) for pattern in patterns)


def instructions(tmp_path: Path) -> tuple[Path, str]:
    app = scratch_app(tmp_path / "app")
    return app, (app / "CLAUDE.md").read_text()


def test_the_scratch_app_tells_the_agent_the_profiles_test_and_lint_commands(
    tmp_path: Path,
) -> None:
    app, text = instructions(tmp_path)

    [test] = PROFILE.test_commands_all(app, root_extras=[])
    lint = PROFILE.lint_command_all_files()
    assert shlex.join(test) in text
    assert shlex.join(lint) in text
    assert shlex.join(test) == "uv run pytest -q --durations=15 --durations-min=3.0 -rfE"
    assert shlex.join(lint) == "uv run pre-commit run --all-files"


def test_the_instruction_file_names_no_bare_test_or_lint_program(tmp_path: Path) -> None:
    _, text = instructions(tmp_path)

    stripped = text.replace("uv run pytest", "").replace("uv run pre-commit", "")
    assert BARE.findall(stripped) == []


def test_both_commands_are_allowed_by_the_profile(tmp_path: Path) -> None:
    app, _ = instructions(tmp_path)

    [test] = PROFILE.test_commands_all(app, root_extras=[])
    assert allowed(test)
    assert allowed(PROFILE.lint_command_all_files())
    assert not allowed(["ruff", "check", "."])


def test_the_instruction_file_is_committed_in_the_start_commit(tmp_path: Path) -> None:
    app, _ = instructions(tmp_path)

    assert "CLAUDE.md" in git(app, "ls-tree", "--name-only", "HEAD").split()
