"""The `acp` adapter agrees with the command policy on where a redirect may land.

An agent that defers its terminal to abk has a redirect onto a tracked file
refused with the policy's own reason and the file left as it was
(spec: command-output-to-files).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide
from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.factories import git, init_repo
from tests.runtimes.acp_agent import requests, use_agent

BRANCH = "spec/add-marker/1"
ALLOWED = {"terminal": "git", "args": ["rev-parse", "--abbrev-ref", "HEAD"]}


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "worktree")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("MARKER = None\n")
    git(path, "checkout", "-q", "-b", BRANCH)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "start")
    # A unit's worktree carries its scratch folder; the rule covers only that.
    (path / ".abk" / "out" / "run-1").mkdir(parents=True)
    return path


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("echo overwritten > src/app.py", id="overwrite"),
        pytest.param("echo overwritten >> src/app.py", id="append"),
        pytest.param("git status && echo overwritten > src/app.py", id="behind-another-command"),
    ],
)
def test_a_redirect_onto_a_tracked_file_is_never_run_and_the_agent_is_told_why(
    tmp_path: Path, worktree: Path, line: str
) -> None:
    record = tmp_path / "agent.jsonl"
    reason = check_command(line, branch=BRANCH, worktree=worktree).reason
    assert reason, f"{line!r} is meant to be one the rules forbid"
    use_agent(record, act=[{"terminal": line, "args": []}, ALLOWED])

    result = AcpRuntime().run(
        AgentRequest(
            prompt="Implement group 1 of add-marker.",
            role="implement",
            cwd=worktree,
            policy=ToolPolicy(),
        )
    )

    assert (worktree / "src" / "app.py").read_text() == "MARKER = None\n"
    refused, allowed = requests(record, "did/terminal")
    assert "error" in refused or refused.get("exitCode") != 0, refused
    assert reason in json.dumps(refused), refused
    assert allowed["output"].strip() == BRANCH
    assert result.ok is True


def test_a_checkout_without_a_scratch_folder_gets_the_same_verdict_from_both_runtimes(
    tmp_path: Path, worktree: Path
) -> None:
    """The redirect rule covers only a checkout that carries a scratch folder: the
    Claude Code hook and the `acp` broker both ask `carries_scratch`."""
    shutil.rmtree(worktree / ".abk")
    line = "echo notes > notes.txt"
    hook = decide(
        {
            "session_id": "s1",
            "cwd": str(worktree),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": line},
        }
    )
    record = tmp_path / "agent.jsonl"
    use_agent(record, act=[{"terminal": line, "args": []}, ALLOWED])

    AcpRuntime().run(
        AgentRequest(
            prompt="Implement group 1 of add-marker.",
            role="implement",
            cwd=worktree,
            policy=ToolPolicy(),
        )
    )

    [reply, _] = requests(record, "did/terminal")
    assert hook is None
    assert "error" not in reply, reply
    assert reply.get("exitCode", 0) == 0, reply
