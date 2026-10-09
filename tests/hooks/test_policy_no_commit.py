"""The hook a turn on a unit's session carries refuses `git commit` as well as `git push`; a
run registered without the option commits as before."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide, hook_settings


def payload(command: str, cwd: Path) -> dict:
    return {
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def command_of(settings: dict) -> str:
    return settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "spec/change/1"], cwd=tmp_path, check=True)
    return tmp_path


def test_a_commit_is_refused_when_the_run_may_not_commit(repo: Path) -> None:
    command = 'git commit -m "fix"'

    assert decide(payload(command, repo)) is None
    answer = decide(payload(command, repo), no_commit=True)

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "commit" in answer["hookSpecificOutput"]["permissionDecisionReason"]


def test_other_commands_are_not_refused_by_the_no_commit_option(repo: Path) -> None:
    assert decide(payload("git status", repo), no_commit=True) is None


def test_the_hook_is_registered_with_committing_refused_only_when_asked() -> None:
    assert "--no-commit" not in command_of(hook_settings(Path("/repo"), no_push=True))
    assert " --no-commit" in command_of(hook_settings(Path("/repo"), no_push=True, no_commit=True))


def test_the_hook_process_refuses_a_commit_given_the_flag(repo: Path) -> None:
    run = subprocess.run(
        [sys.executable, "-m", "agent_build_kit.hooks.policy", "--no-commit"],
        input=json.dumps(payload('git commit -m "x"', repo)),
        capture_output=True,
        text=True,
        check=True,
    )

    assert '"deny"' in run.stdout


def test_a_free_sessions_hook_refuses_only_commit_and_push(repo: Path) -> None:
    """The person's own session, run by the server: none of the pipeline's rules, so a merge
    they ask for is theirs to make, and a commit or push is refused because the server
    started the process."""
    free = dict(refusals_only=True, no_push=True, no_commit=True)

    assert decide(payload("gh pr merge 4", repo), **free) is None
    assert decide(payload("git push --force origin main", repo), **free) is not None
    assert decide(payload('git commit -m "x"', repo), **free) is not None
    assert decide(payload("git push origin spec/change/1", repo), **free) is not None


def test_the_free_hook_is_registered_without_the_units_scope() -> None:
    settings = hook_settings(None, refusals_only=True, no_push=True, no_commit=True)

    command = command_of(settings)
    assert "--refusals-only" in command
    assert "--no-commit" in command and "--no-push" in command
    assert "--specs" not in command
