"""The python-uv profile's tool list lets a builder manage the lock and the environment
of its project, and nothing that installs outside the project."""

from __future__ import annotations

import re

import pytest

from agent_build_kit.profiles.python_uv import PythonUvProfile


def allows(tool_list: str, command: str) -> bool:
    """Claude Code's `Bash(...)` matching: `*` stands for anything and the pattern
    covers the whole command."""
    patterns = re.findall(r"Bash\(([^)]*)\)", tool_list)
    return any(
        re.fullmatch(".*".join(re.escape(part) for part in pattern.split("*")), command)
        for pattern in patterns
    )


@pytest.mark.parametrize(
    "command",
    [
        "uv lock",
        "uv lock --upgrade-package pyrefly",
        "uv sync --locked",
        "uv add pydantic",
        "uv remove pydantic",
    ],
)
def test_a_builder_may_run(command: str) -> None:
    assert allows(PythonUvProfile.allowed_tools, command)


@pytest.mark.parametrize(
    "command",
    [
        "uv publish",
        "uv tool install ruff",
        "uv python install 3.13",
        "uv pip install requests",
    ],
)
def test_a_builder_that_can_lock_still_may_not_leave_the_project(command: str) -> None:
    tools = PythonUvProfile.allowed_tools
    assert allows(tools, "uv lock")
    assert not allows(tools, command)


@pytest.mark.parametrize("command", ["uv run pytest", "pre-commit run --all-files"])
def test_a_builder_that_can_lock_may_still_run(command: str) -> None:
    tools = PythonUvProfile.allowed_tools
    assert allows(tools, "uv lock")
    assert allows(tools, command)
