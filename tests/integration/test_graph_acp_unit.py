"""One real unit built end to end through the graph, then reworked on a comment.

The runtime is a real agent on this host (`ABK_ACCEPTANCE_ACP_COMMAND`) and
`abk tick` is the real CLI run as a process, against a scratch planning repo and
a scratch code repo with a bare remote. Only the forge is faked, at the
command's own boundary: a `gh` script on PATH that prints what `gh` prints, from
a small state directory the test edits. The test posts the review comment and
the merge by writing to that directory, as a reviewer would on the host.

What is asserted is what an operator sees: the unit's thread is in the
checkpoint store, waiting in review, after the first tick; a comment resumes it
into rework and a second push; and the thread is gone once the pull request is
merged.

Needs an agent speaking the protocol, node for the OpenSpec CLI and uv. Bills on
demand and takes minutes, so it is marked tier 2 and excluded from the default
suite.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from tests.factories import git, init_repo, scratch_app

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

CHANGE = "add-marker"
BRANCH = f"spec/{CHANGE}/1"
UNIT_ID = f"{CHANGE}/1"
AGENT_COMMAND = "ABK_ACCEPTANCE_ACP_COMMAND"
COMMENT = "Please add a one-line docstring to `marker()` saying what it returns."

# The forge, as `gh` prints it. `FORGE` is a directory: `created` exists once a
# pull request has been opened, `merged` exists once the test has merged the
# pull request. An inline review comment is one state in three wire shapes, each
# a file the test writes: `review.json` (the submitted review as `gh pr list
# --json reviews` prints it), and `rest_review.json` and `rest_comment.json`
# (the same review and its comment as the REST API prints them).
FAKE_GH = """#!/bin/sh
echo "$@" >> "$GH_CALLS"
cd "$FORGE" || exit 1
case "$1 $2" in
  "pr list")
    if ! [ -e created ]; then echo '[]'; exit 0; fi
    case "$*" in
      *"--head "*) echo '[{"number": 7}]' ;;
      *)
        merged=null
        [ -e merged ] && merged='"2026-01-02T00:00:00Z"'
        state=OPEN
        [ -e merged ] && state=MERGED
        reviews='[]'
        [ -e review.json ] && reviews="[$(cat review.json)]"
        printf '[{"number": 7, "headRefName": "%s", "baseRefName": "main", "state": "%s", ' \
          "$BRANCH" "$state"
        printf '"isDraft": false, "mergedAt": %s, "labels": [], "comments": [], ' "$merged"
        printf '"statusCheckRollup": [], "reviewDecision": "", "reviews": %s, ' "$reviews"
        printf '"mergeable": "MERGEABLE"}]\\n'
        ;;
    esac ;;
  "pr create") touch created; echo 'https://github.com/example/app/pull/7' ;;
  "auth token") echo 'token' ;;
  "api --paginate")
    case "$3" in
      */pulls/7/comments)
        if [ -e rest_comment.json ]; then echo "[$(cat rest_comment.json)]"; else echo '[]'; fi ;;
      */pulls/7/reviews)
        if [ -e rest_review.json ]; then echo "[$(cat rest_review.json)]"; else echo '[]'; fi ;;
      *) echo '[]' ;;
    esac ;;
  *) echo '{}' ;;
esac
"""

TASKS = """# Tasks

## 1. [app] [tier1] Add the marker

- [ ] 1.1 Test: `marker()` in `src/app/marker.py` returns the string `"marked"`.
- [ ] 1.2 Add `marker()` to `src/app/marker.py`.

Acceptance: none — a single function whose own test is its proof
"""


class Ticked(Frozen):
    returncode: int
    output: str


class Scratch(Frozen):
    planning: Path
    remote: Path
    state: Path
    forge: Path
    env: dict[str, str]


@pytest.fixture(scope="module")
def scratch(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Scratch]:
    tmp_path = tmp_path_factory.mktemp("graph-acp")
    command = os.environ.get(AGENT_COMMAND, "")
    if not command:
        pytest.fail(f"{AGENT_COMMAND} names no agent: this run needs a real one on the host")

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    app = scratch_app(tmp_path / "app")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "-q", "origin", "main")

    planning = init_repo(tmp_path / "planning")
    change = planning / "openspec" / "changes" / CHANGE
    (change / "specs" / "marker").mkdir(parents=True)
    (planning / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
    (change / "proposal.md").write_text(
        "## Why\n\nThe app needs a marker.\n\n## What Changes\n\n- Add `marker()`.\n\n"
        "## Impact\n\n- app: one module.\n"
    )
    (change / "specs" / "marker" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: A marker\nThe app SHALL expose `marker()`.\n\n"
        "#### Scenario: Reading it\n- **WHEN** `marker()` is called\n"
        '- **THEN** it returns "marked"\n'
    )
    (change / "tasks.md").write_text(TASKS)
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    slug: example/app\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"runtimes:\n  acp:\n    command: {shlex.split(command)}\n"
    )
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    forge = tmp_path / "forge"
    forge.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_CALLS": str(tmp_path / "gh-calls.txt"),
        "FORGE": str(forge),
        "BRANCH": BRANCH,
        "ABK_CONFIG": str(planning / "abk.yaml"),
        "ABK_WORKTREE_ROOT": str(tmp_path / "worktrees"),
        "ABK_RUNTIME": "acp",
    }
    yield Scratch(
        planning=planning,
        remote=remote,
        state=Installation(config.load(planning / "abk.yaml"), planning).state_dir,
        forge=forge,
        env=env,
    )


def tick(scratch: Scratch) -> Ticked:
    run = subprocess.run(
        [str(Path(sys.executable).parent / "abk"), "tick"],
        cwd=scratch.planning,
        env=scratch.env,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    return Ticked(returncode=run.returncode, output=run.stdout + run.stderr)


def thread_next(scratch: Scratch) -> tuple[Node, ...] | None:
    """Where the unit's thread stands in the checkpoint store: the nodes still
    to run, or None when there is no thread."""

    async def look() -> tuple[Node, ...] | None:
        async with open_checkpointer(unit_graphs_path(scratch.state)) as saver:
            position = await thread_position(saver, UNIT_ID)
            return None if position.state is None else position.next

    return asyncio.run(look())


def commits_on_branch(scratch: Scratch) -> list[str]:
    return git(scratch.remote, "log", "--format=%H", f"main..{BRANCH}").split()


def run_log(scratch: Scratch) -> str:
    logs = sorted((scratch.state / "unit-logs").glob(f"{CHANGE}-01-*.log"))
    return "\n".join(path.read_text() for path in logs)


def test_a_unit_runs_to_review_is_reworked_on_a_comment_and_its_thread_ends_at_merge(
    scratch: Scratch,
) -> None:
    built = tick(scratch)
    assert built.returncode == 0, built.output
    first = commits_on_branch(scratch)
    assert first, f"{BRANCH} never reached the remote\n{built.output}\n{run_log(scratch)}"
    assert "pr create" in Path(scratch.env["GH_CALLS"]).read_text()
    # Waiting in review is a thread parked at its wait, not a finished one.
    assert thread_next(scratch) == (Node.AWAIT_REVIEW,), run_log(scratch)

    # A tick with nothing new changes nothing: the poller records the pull
    # request's comments as seen before the reviewer writes one.
    quiet = tick(scratch)
    assert quiet.returncode == 0, quiet.output
    assert commits_on_branch(scratch) == first
    assert thread_next(scratch) == (Node.AWAIT_REVIEW,)

    review = {
        "id": "PRR_kwDOexample5001",
        "state": "COMMENTED",
        "author": {"login": "reviewer"},
        "body": "",
        "submittedAt": "2026-01-01T00:00:00Z",
    }
    rest_review = {
        "id": 5001,
        "node_id": "PRR_kwDOexample5001",
        "state": "COMMENTED",
        "user": {"login": "reviewer"},
        "body": "",
        "submitted_at": "2026-01-01T00:00:00Z",
    }
    rest_comment = {
        "id": 9001,
        "node_id": "PRRC_kwDOexample9001",
        "pull_request_review_id": 5001,
        "body": COMMENT,
        "path": "src/app/marker.py",
        "line": 1,
        "user": {"login": "reviewer"},
    }
    (scratch.forge / "review.json").write_text(json.dumps(review))
    (scratch.forge / "rest_review.json").write_text(json.dumps(rest_review))
    (scratch.forge / "rest_comment.json").write_text(json.dumps(rest_comment))
    reworked = tick(scratch)
    assert reworked.returncode == 0, reworked.output
    second = commits_on_branch(scratch)
    assert len(second) > len(first), f"no rework was pushed\n{reworked.output}\n{run_log(scratch)}"
    assert set(first) <= set(second), "the rework rewrote what was already pushed"
    # Only the comment asks for a docstring: the rework that read it wrote one.
    marker = git(scratch.remote, "show", f"{BRANCH}:src/app/marker.py")
    assert '"""' in marker, f"the rework did not act on the comment\n{marker}\n{run_log(scratch)}"
    assert thread_next(scratch) == (Node.AWAIT_REVIEW,), run_log(scratch)

    (scratch.forge / "merged").touch()
    merged = tick(scratch)
    assert merged.returncode == 0, merged.output
    assert thread_next(scratch) is None, "the thread outlived the merge"
