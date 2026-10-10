"""The scratch app the tier-2 build test plans against has a working tier 1.

Its tier 1 is the python-uv profile's own commands, run on a real repo with no
agent, so the fixture cannot drift from the profile unnoticed: a missing
`pre-commit`, or a hook config that wants the network, fails here in seconds
rather than at the end of a billed agent run.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.factories import git, scratch_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]


def test_the_scratch_apps_tier1_commands_succeed_as_the_fixture_is_built(tmp_path: Path) -> None:
    app = scratch_app(tmp_path / "app")
    # What a unit adds: a test, so pytest has something to collect.
    (app / "tests" / "test_marker.py").write_text("def test_it():\n    assert True\n")
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "a test")
    profile = profiles.get("python-uv")

    commands = [
        profile.lint_command("HEAD~1"),
        *profile.test_commands(app, ["tests/test_marker.py"], root_extras=[]),
    ]

    for command in commands:
        result = subprocess.run(command, cwd=app, capture_output=True, text=True)
        assert result.returncode == 0, f"{command}\n{result.stdout}\n{result.stderr}"


def test_the_scratch_apps_tier1_commands_leave_nothing_for_git_to_report(tmp_path: Path) -> None:
    """A file the commands create and the repo does not commit would hold a unit.

    The first `uv run` writes `uv.lock`; the fixture ignores it because resolving
    one needs the network, so git's view of the worktree stays clean.
    """
    app = scratch_app(tmp_path / "app")
    (app / "tests" / "test_marker.py").write_text("def test_it():\n    assert True\n")
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "a test")
    profile = profiles.get("python-uv")

    commands = [
        profile.lint_command("HEAD~1"),
        *profile.test_commands(app, ["tests/test_marker.py"], root_extras=[]),
    ]
    for command in commands:
        result = subprocess.run(command, cwd=app, capture_output=True, text=True)
        assert result.returncode == 0, f"{command}\n{result.stdout}\n{result.stderr}"

    assert (app / "uv.lock").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=app,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == ""
