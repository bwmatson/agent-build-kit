"""Conflict resolution reaches its agent through the runtime seam.

The resolver used to run `claude` itself and ignore how the process ended, so
a run the account had no room for looked exactly like one that found nothing
to change: the markers stayed, the move was abandoned as a conflict, and the
unit went back to be ported by hand. Through the runtime, a refusal is a rate
limit — the tick pauses on it — and any other failed run stops the move
saying the resolver failed.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.pipeline import restack
from agent_build_kit.pipeline.restack import RestackConflict, resolved_move
from agent_build_kit.pipeline.usage_guard import RateLimited
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.factories import git, init_repo
from tests.runtimes.claude_cli import FakeClaude, failed_build, refused
from tests.runtimes.stand_in import StandInRuntime
from tests.runtimes.test_claude_code_argv import RESOLVER_TOOLS, flags


def commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"write {name}")


@pytest.fixture
def conflicting(tmp_path: Path) -> Path:
    """main and spec/c/2 both change markers.py, in different ways."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "markers.py", "markers = []\n")
    git(repo, "checkout", "-q", "-b", "spec/c/1")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    commit(repo, "markers.py", 'markers = ["local_stack"]\n')
    git(repo, "checkout", "-q", "main")
    commit(repo, "markers.py", 'markers = ["integration"]\n')
    return repo


def move(repo: Path, **kwargs) -> restack.Moved:
    return resolved_move(
        repo,
        "spec/c/2",
        new_base="main",
        old_base="spec/c/1",
        moving_unit="add-marker/2",
        moving_intent="Register the local_stack marker in app",
        onto_unit="add-integration/1",
        onto_intent="Register the integration marker in app",
        **kwargs,
    )


def keeps_both(request: AgentRequest) -> None:
    assert request.cwd is not None
    (request.cwd / "markers.py").write_text('markers = ["integration", "local_stack"]\n')


def test_conflict_resolution_runs_through_the_runtime_it_is_given(conflicting: Path) -> None:
    runtime = StandInRuntime(act=keeps_both)

    moved = move(conflicting, resolve=partial(restack.claude_resolver, runtime=runtime))

    assert moved.resolved == ("markers.py",)
    request = runtime.request
    assert request.cwd == conflicting
    assert "add-marker/2" in request.prompt
    assert "Register the integration marker in app" in request.prompt
    # It edits because its tool list says so, and is granted nothing more.
    assert request.allowed_tools == RESOLVER_TOOLS
    assert request.permission_mode == "allowed_tools_only"


def test_under_claude_code_the_resolver_sends_the_command_it_sent_before(tmp_path: Path) -> None:
    fake = FakeClaude(stdout="Resolved both conflicts.")

    restack.claude_resolver(
        "Resolve the conflicts.", cwd=tmp_path, runtime=ClaudeCodeRuntime(execute=fake)
    )

    assert flags(fake.argv, "Resolve the conflicts.") == {
        "-p": None,
        "--allowedTools": RESOLVER_TOOLS,
        "--output-format": "text",
    }
    assert fake.calls[0][1] == tmp_path


def test_a_resolution_refused_for_a_spent_window_is_a_rate_limit(conflicting: Path) -> None:
    """Not a conflict nobody could resolve: the tick pauses until the window
    resets, and the branch is left exactly where it was, with no rebase in
    progress, for the restack to be tried again then."""
    before = git(conflicting, "rev-parse", "spec/c/2")
    fake = FakeClaude(
        stdout=refused(conflicting, "Claude AI usage limit reached|1919763200"), returncode=1
    )

    with pytest.raises(RateLimited) as caught:
        move(
            conflicting,
            resolve=partial(restack.claude_resolver, runtime=ClaudeCodeRuntime(execute=fake)),
        )

    assert not isinstance(caught.value, RestackConflict)
    assert caught.value.resets_at is not None
    assert caught.value.resets_at.year == 2030
    assert len(fake.calls) == 1, "a refusal is not retried"
    assert not (conflicting / ".git" / "rebase-merge").exists()
    assert git(conflicting, "rev-parse", "spec/c/2") == before


def test_a_resolution_that_fails_stops_the_move_naming_the_resolver(conflicting: Path) -> None:
    """A run that broke is not a resolution that left the markers in: the
    move stops on what the CLI said went wrong."""
    fake = FakeClaude(
        stdout=failed_build(conflicting, "Stream closed before the turn ended"), returncode=1
    )

    with pytest.raises(RestackConflict, match="conflict resolver failed") as caught:
        move(
            conflicting,
            resolve=partial(restack.claude_resolver, runtime=ClaudeCodeRuntime(execute=fake)),
        )

    assert "Stream closed before the turn ended" in str(caught.value)
    assert not (conflicting / ".git" / "rebase-merge").exists()


def test_with_no_runtime_given_resolution_uses_the_active_one(conflicting: Path) -> None:
    """Not a `claude` process of its own: the default resolver runs the
    workspace's runtime, whose real executor the suite refuses."""
    with pytest.raises((RestackConflict, AssertionError), match="inject `execute=`"):
        move(conflicting)
