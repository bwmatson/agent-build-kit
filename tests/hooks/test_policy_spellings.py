"""The runtime that answers without a prompt holds for every spelling: each
judge row of the table, run through the policy hook's entry, is denied.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide
from tests.spelling_rows import judge_rows


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "spec/change/1"], cwd=tmp_path, check=True)
    return tmp_path


def test_every_spelling_of_the_table_is_denied_by_the_hook(repo: Path) -> None:
    allowed = []
    for _label, spelling in judge_rows():
        answer = decide(
            {
                "session_id": "s1",
                "cwd": str(repo),
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": spelling.command},
            }
        )
        if answer is None or answer["hookSpecificOutput"]["permissionDecision"] != "deny":
            allowed.append(spelling.command)
    assert allowed == []
