"""A refusal reaches the operator as one progress line naming the command, the
rule's reason and the layer that made it, so they know what to tighten: abk's
command rules, or the agent's own configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.factories import git, init_repo
from tests.runtimes.acp_agent import use_agent

BRANCH = "spec/add-marker/1"
LINE = "git commit --amend --no-edit"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "worktree")
    git(path, "checkout", "-q", "-b", BRANCH)
    return path


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    path = tmp_path / "planning" / "openspec" / "specs"
    path.mkdir(parents=True)
    return path


def _refusals(record: Path, worktree: Path, specs: Path, **agent: Any) -> list[str]:
    lines: list[str] = []
    use_agent(record, **agent)
    AcpRuntime().run(
        AgentRequest(
            prompt="Implement group 1 of add-marker.",
            role="implement",
            cwd=worktree,
            add_dirs=(specs,),
            policy=ToolPolicy(specs_dir=specs),
            on_event=lines.append,
        )
    )
    return [line.strip() for line in lines if "refused" in line]


def _expected(layer: str) -> list[str]:
    reason = check_command(LINE, branch=BRANCH).reason
    assert reason
    return [f"refused `{LINE}` by {layer}: {reason}"]


def test_a_terminal_refusal_names_its_layer(tmp_path: Path, worktree: Path, specs: Path) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"terminal": "git", "args": ["commit", "--amend", "--no-edit"]}],
    )

    assert refusals == _expected("abk's command rules")


def test_a_terminal_refusal_is_not_also_the_agents_own(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[
            {
                "terminal": "git",
                "args": ["commit", "--amend", "--no-edit"],
                "raw_input": {"command": "git commit --amend"},
            }
        ],
    )

    assert refusals == _expected("abk's command rules")


def test_a_permission_refusal_names_its_layer(tmp_path: Path, worktree: Path, specs: Path) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl", worktree, specs, act=[{"ask": "execute", "command": LINE}]
    )

    assert refusals == _expected("abk's command rules")


def test_the_cancel_path_names_its_layer(tmp_path: Path, worktree: Path, specs: Path) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"ask": "execute", "command": LINE, "options": ["allow_once", "allow_always"]}],
    )

    assert refusals == _expected("abk's command rules")


def test_a_forbidden_command_the_agent_failed_on_its_own_names_its_configuration(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"unasked": LINE, "status": "failed"}],
    )

    assert refusals == _expected("the agent's own configuration")


def test_an_allowed_command_that_fails_is_not_called_a_refusal(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"unasked": "git status", "status": "failed"}],
    )

    assert refusals == []


def test_a_command_the_agent_blocked_by_its_own_rules_names_its_policy(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """No permission request reached the client: the agent refused it itself
    and says so in the output of the call that failed."""
    output = "Blocked by the user-defined deny rule `git commit *--amend*`"

    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"unasked": LINE, "status": "failed", "output": output}],
    )

    assert refusals == [f"refused `{LINE}` by the agent's own policy: {output}"]


def test_a_failed_command_whose_output_does_not_say_it_was_blocked_is_not_the_agents_policy(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"unasked": "git status", "status": "failed", "output": "fatal: not a repository"}],
    )

    assert refusals == []


def test_an_unasked_command_failing_with_the_shells_permission_denied_is_not_a_refusal(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    output = "ls: cannot open directory '/root': Permission denied"

    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"unasked": "ls /root", "status": "failed", "output": output}],
    )

    assert refusals == []


def test_an_allowed_command_abk_ran_that_fails_saying_forbidden_is_not_a_refusal(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """The client's terminal ran it; an HTTP 403 Forbidden is
    the command's own result, not a policy."""
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[
            {
                "terminal": "sh",
                "args": ["-c", "echo 403 Forbidden; exit 1"],
                "raw_input": {"command": "uv run pytest"},
            }
        ],
    )

    assert refusals == []


def test_a_command_abk_ran_that_prints_the_agents_refusal_wording_is_not_a_refusal(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """Only the marking made when abk starts the command keeps it out of the
    agent's policy: the output here matches the agent's own refusal wording."""
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[
            {
                "terminal": "sh",
                "args": ["-c", "echo 'Blocked by the user-defined deny rule Bash(x)'; exit 1"],
                "raw_input": {"command": "uv run pytest"},
            }
        ],
    )

    assert refusals == []


def test_an_agent_run_failure_with_a_denial_worded_line_mid_output_is_not_a_refusal(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """The agent ran `uv run pytest` itself and a test's own assertion says
    permission was denied: a line of the command's output, not the agent's verdict."""
    output = "FAILED tests/test_acl.py\nE   AssertionError: Permission for guest was denied\n"
    for act in (
        {"unasked": "uv run pytest", "status": "failed", "output": output},
        {"titled_terminal": "uv run pytest", "output": output},
    ):
        refusals = _refusals(tmp_path / "agent.jsonl", worktree, specs, act=[act])

        assert refusals == []


TITLED_DENIAL = (
    "BLOCKED: this command matches the user-defined deny rule 'git commit *--amend*'. "
    "It cannot be executed. Do NOT retry or rephrase this command. The user has explicitly "
    "forbidden it, and no flag, mode or wording of the request will change that: choose "
    "another way to reach the same end, or stop and say what you were trying to do."
)


def test_a_titled_terminal_denial_names_the_command_and_the_agents_policy(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    """A terminal call that sends no raw input: the command is in the
    start's `$ ` line and title, the denial in the failed end's text."""
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"titled_terminal": LINE, "output": TITLED_DENIAL}],
    )

    assert len(refusals) == 1
    assert f"refused `{LINE}` by the agent's own policy" in refusals[0]
    assert "amend" in refusals[0]
    assert "deny rule 'git commit *--amend*'" in refusals[0]
    assert len(refusals[0].split("policy: ", 1)[1]) <= 200


def test_a_batched_titled_terminal_denial_is_named_for_the_command_abk_forbids(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"titled_terminal": LINE, "also": 1, "output": TITLED_DENIAL}],
    )

    assert len(refusals) == 1
    assert f"refused `{LINE}` by the agent's own policy" in refusals[0]


def test_a_batched_titled_terminal_denial_tied_to_no_command_is_logged_against_the_first(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"titled_terminal": "git status", "also": 1, "output": TITLED_DENIAL}],
    )

    assert len(refusals) == 1
    assert "refused `git status (part of a batch)` by the agent's own policy" in refusals[0]


def test_a_titled_terminal_failure_that_is_not_a_denial_is_not_the_agents_policy(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"titled_terminal": "git status", "output": "fatal: not a git repository"}],
    )
    assert refusals == []

    refusals = _refusals(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        act=[{"titled_terminal": LINE, "output": "error: nothing to amend"}],
    )
    assert refusals == _expected("the agent's own configuration")
