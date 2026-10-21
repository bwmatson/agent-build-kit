"""One real unit built end to end through the graph, then reworked on a comment.

The runtime is a real Claude Code agent on this host and
`abk tick` is the real CLI run as a process, against a scratch planning repo and
a scratch code repo with a bare remote. Only the host is faked: a fake GitHub
server speaking the REST API, reached through `ABK_GITHUB_API_URL`, with `gh auth
token` the one command left as a script. The test posts the review comment and
the merge to the server, as a reviewer would on the host.

What is asserted is what an operator sees: the unit's thread is in the
checkpoint store, waiting in review, after the first tick; a comment resumes it
into rework and a second push; and the thread is gone once the pull request is
merged.

Needs an agent speaking the protocol, node for the OpenSpec CLI and uv. Bills on
demand and takes minutes, so it is marked e2e-test and excluded from the default
suite.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.factories import git
from tests.forges.github_server import FakeGitHub
from tests.marker_scratch import (
    BRANCH,
    TASKS,
    Scratch,
    build_scratch,
    run_log,
    serving_host,
    thread_next,
)
from tests.runtime_scratch import CLAUDE_CODE_PARAMS, runtime_scratch
from tests.scratch_tick import commits_on_unit_branch, run_tick

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

COMMENT = "Please add a one-line docstring to `marker()` saying what it returns."


@pytest.fixture(scope="module")
def github_host() -> Iterator[FakeGitHub]:
    yield from serving_host()


@pytest.fixture(scope="module")
def scratch_ledger(scratch: Scratch) -> Path:
    """The scratch installation's usage ledger, for the time split of each phase."""
    return scratch.state / LEDGER_NAME


@pytest.fixture(scope="module")
def scratch(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    github_host: FakeGitHub,
) -> Scratch:
    """The scratch installation for the runtime the test is parametrized with."""
    runtime = runtime_scratch(request.param, tmp_path_factory, lambda command: None)
    return build_scratch(tmp_path_factory.mktemp("graph-unit"), github_host, runtime, tasks=TASKS)


@pytest.mark.parametrize("scratch", CLAUDE_CODE_PARAMS, indirect=True)
def test_a_unit_runs_to_review_is_reworked_on_a_comment_and_its_thread_ends_at_merge(
    scratch: Scratch,
    scratch_ledger: Path,
) -> None:
    built = run_tick(scratch)
    assert built.returncode == 0, built.output
    first = commits_on_unit_branch(scratch, BRANCH, built)
    assert scratch.host.requests("POST", "/repos/example/app/pulls"), (
        f"no pull request was opened\n{built.output}"
    )
    # Waiting in review is a thread parked at its wait, not a finished one.
    assert thread_next(scratch.state) == (Node.AWAIT_REVIEW,), (
        f"{run_log(scratch.state)}\n{built.output}"
    )

    # A tick with nothing new changes nothing: the poller records the pull
    # request's comments as seen before the reviewer writes one.
    quiet = run_tick(scratch)
    assert quiet.returncode == 0, quiet.output
    assert commits_on_unit_branch(scratch, BRANCH, quiet) == first, quiet.output
    assert thread_next(scratch.state) == (Node.AWAIT_REVIEW,), quiet.output

    comment = scratch.host.add_review(7, "COMMENTED", "", inline=("src/app/marker.py", 1, COMMENT))
    reworked = run_tick(scratch)
    assert reworked.returncode == 0, reworked.output
    second = commits_on_unit_branch(scratch, BRANCH, reworked)
    assert len(second) > len(first), (
        f"no rework was pushed\n{reworked.output}\n{run_log(scratch.state)}"
    )
    assert set(first) <= set(second), "the rework rewrote what was already pushed"
    # Only the comment asks for a docstring: the rework that read it wrote one.
    marker = git(scratch.remote, "show", f"{BRANCH}:src/app/marker.py")
    assert '"""' in marker, (
        f"the rework did not act on the comment\n{marker}\n{run_log(scratch.state)}"
    )
    # The agent answered in the comment's own thread, not under the review.
    thread = scratch.host.review_comments(7)
    assert any(c.get("in_reply_to_id") == comment for c in thread), (
        f"no reply in the comment's thread\n{thread}\n{run_log(scratch.state)}\n{reworked.output}"
    )
    assert thread_next(scratch.state) == (Node.AWAIT_REVIEW,), (
        f"{run_log(scratch.state)}\n{reworked.output}"
    )

    scratch.host.merge(7)
    merged = run_tick(scratch)
    assert merged.returncode == 0, merged.output
    assert thread_next(scratch.state) is None, f"the thread outlived the merge\n{merged.output}"
