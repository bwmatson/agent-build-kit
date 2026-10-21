"""One real unit built, reviewed in the UI and merged by a person, with no code host.

The runtime is a real Claude Code agent on this host and `abk
tick` is the real CLI run as a process, against a scratch planning repo and a
scratch code repo that has no remote at all and sets `forge: local`. Nothing is
faked: the reviewer's comment and decision go through the web UI's own endpoints, and
the merge is a `git merge` in the code repo, as a person would run it.

What is asserted is what an operator sees: the unit's branch and pull request exist
only locally; a UI comment sends the unit back and the rework answers it; the
approval is recorded and leaves the pull request open; and once the branch is
merged with git the unit is recorded merged and the unit that depended on it starts.

Needs an agent speaking the protocol, node for the OpenSpec CLI and uv. Bills on
demand and takes minutes, so it is an e2e-test and excluded from the default
suite.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import Field

from agent_build_kit import config
from agent_build_kit.forges.local import LocalForge
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, MERGED
from agent_build_kit.serve.review import ReviewStore
from agent_build_kit.serve.server import create_app
from tests.factories import git, init_repo, scratch_app
from tests.runtime_scratch import runtime_scratch
from tests.scratch_tick import commits_on_unit_branch, run_tick

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.runtime_claude_code,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

CHANGE = "add-marker"
FIRST = f"{CHANGE}/1"
SECOND = f"{CHANGE}/2"
BRANCH = f"spec/{FIRST}"
NEXT_BRANCH = f"spec/{SECOND}"
COMMENT = "Please add a one-line docstring to `marker()` saying what it returns."

TASKS = """# Tasks

## 1. [app] [unit-test] Add the marker

- [ ] 1.1 Test: `marker()` in `src/app/marker.py` returns the string `"marked"`.
- [ ] 1.2 Add `marker()` to `src/app/marker.py`.

Acceptance: none — a single function whose own test is its proof

## 2. [app] [unit-test] Add the second marker

- [ ] 2.1 Test: `second()` in `src/app/second.py` returns `marker() + "-second"`, where
  `marker` is imported from `app.marker`.
- [ ] 2.2 Add `second()` to `src/app/second.py`, built on `marker()` from group 1.

Acceptance: none — a single function whose own test is its proof
"""


class Scratch(Frozen):
    model_config = {"arbitrary_types_allowed": True}

    planning: Path
    app: Path
    # Where the unit's branch is kept: the code repo itself, which has no remote.
    remote: Path
    state: Path
    env: dict[str, str] = Field(repr=False)
    installation: Installation


@pytest.fixture(scope="module")
def scratch(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Scratch]:
    tmp_path = tmp_path_factory.mktemp("local-forge")
    runtime = runtime_scratch("claude_code", tmp_path_factory, lambda command: None)

    app = scratch_app(tmp_path / "app")
    assert git(app, "remote").strip() == "", "the scratch app must have no remote"

    planning = init_repo(tmp_path / "planning")
    change = planning / "openspec" / "changes" / CHANGE
    (change / "specs" / "marker").mkdir(parents=True)
    (planning / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
    (change / "proposal.md").write_text(
        "## Why\n\nThe app needs markers.\n\n"
        "## What Changes\n\n- Add `marker()` and `second()`.\n\n"
        "## Impact\n\n- app: two modules.\n"
    )
    (change / "specs" / "marker" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: A marker\nThe app SHALL expose `marker()`.\n\n"
        "#### Scenario: Reading it\n- **WHEN** `marker()` is called\n"
        '- **THEN** it returns "marked"\n'
    )
    (change / "tasks.md").write_text(TASKS)
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    forge: local\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"{runtime.runtimes_yaml}"
        # Size must not push the planner to fold the two small groups into one unit.
        "limits:\n  min_unit_lines: 1\n"
    )
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")

    installation = Installation(config.load(planning / "abk.yaml"), planning)
    env = {
        **{k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "ABK_GH_TOKEN")},
        **runtime.env,
        "ABK_CONFIG": str(planning / "abk.yaml"),
        "ABK_WORKTREE_ROOT": str(tmp_path / "worktrees"),
    }
    yield Scratch(
        planning=planning,
        app=app,
        remote=app,
        state=installation.state_dir,
        env=env,
        installation=installation,
    )


def branches(scratch: Scratch) -> list[str]:
    return git(scratch.app, "branch", "--format=%(refname:short)").split()


def unit_state(scratch: Scratch, unit_id: str) -> str:
    return str(UnitStore(scratch.state / "units.json").get(unit_id).state)


def run_log(scratch: Scratch) -> str:
    logs = sorted((scratch.state / "unit-logs").glob(f"{CHANGE}-*.log"))
    return "\n".join(path.read_text() for path in logs)


def test_a_unit_is_reviewed_in_the_ui_reworked_approved_and_merged_by_a_person_with_git(
    scratch: Scratch,
) -> None:
    reviews = ReviewStore(scratch.state / "reviews")

    built = run_tick(scratch)
    assert built.returncode == 0, built.output
    first = commits_on_unit_branch(scratch, BRANCH)
    assert first, f"{BRANCH} was never built in the local repo\n{built.output}\n{run_log(scratch)}"
    assert (scratch.state / "local-prs.json").exists(), "no local pull request was recorded"
    assert unit_state(scratch, FIRST) == str(IN_REVIEW), (
        f"the built unit did not reach review\n{built.output}\n{run_log(scratch)}"
    )
    assert git(scratch.app, "remote").strip() == "", "the build gave the repo a remote"
    planned = UnitStore(scratch.state / "units.json")
    assert SECOND in [u.id for u in planned.all()], (
        "the planner did not make the second group a unit of its own"
    )
    assert FIRST in planned.get(SECOND).depends_on, (
        "the planner did not make the second unit depend on the first"
    )

    # A comment posted to the web UI's endpoint sends the unit back.
    ui = TestClient(create_app(scratch.installation))
    posted = ui.post(
        f"/api/units/{CHANGE}/1/review/threads",
        json={"path": "src/app/marker.py", "side": "new", "line": 1, "body": COMMENT},
    )
    assert posted.status_code == 200, posted.text
    thread_id = posted.json()["id"]
    reworked = run_tick(scratch)
    assert reworked.returncode == 0, reworked.output
    second = commits_on_unit_branch(scratch, BRANCH)
    assert len(second) > len(first), f"no rework\n{reworked.output}\n{run_log(scratch)}"
    assert unit_state(scratch, FIRST) == str(IN_REVIEW), (
        f"the reworked unit did not return to review\n{reworked.output}\n{run_log(scratch)}"
    )
    assert set(first) <= set(second), "the rework rewrote what was already committed"
    marker = git(scratch.app, "show", f"{BRANCH}:src/app/marker.py")
    assert '"""' in marker, f"the rework did not act on the comment\n{marker}\n{run_log(scratch)}"
    answered = [t for t in reviews.read(FIRST).threads if t.id == thread_id]
    assert answered
    assert answered[0].replies, f"the comment was not answered\n{run_log(scratch)}"

    # Approve is recorded and is not a merge.
    decided = ui.put(
        f"/api/units/{CHANGE}/1/review/decision",
        json={"decision": "approve", "summary": "Looks good."},
    )
    assert decided.status_code == 200, decided.text
    approved = run_tick(scratch)
    assert approved.returncode == 0, approved.output
    assert unit_state(scratch, FIRST) == str(IN_REVIEW), (
        f"approving moved the unit out of review\n{approved.output}\n{run_log(scratch)}"
    )
    scratch.installation.activate()  # list against git as the pipeline's own listing does
    forge = LocalForge(scratch.state)
    repo = forge.identity(scratch.installation.config.repos["app"])
    [pull] = forge.list_prs(repo, head_prefix=BRANCH)
    assert pull.state == "open", f"approving closed the pull request: {pull.state}"
    assert pull.review_decision == "approved", (
        f"the approval did not reach the pull request: {pull}"
    )

    # A person merges with git.
    dependent_started = NEXT_BRANCH in branches(scratch)
    before = forge.list_prs(repo, head_prefix=NEXT_BRANCH)
    if before:
        assert len(before) == 1, f"the dependent has several pull requests: {before}"
        assert before[0].base == BRANCH, (
            f"the dependent's pull request did not target the first unit: {before[0].base}"
            f"\n{approved.output}"
        )
    git(scratch.app, "merge", "--no-ff", "-q", "-m", "merge the marker", BRANCH)
    merged = run_tick(scratch)
    assert merged.returncode == 0, merged.output
    context = f"\n{merged.output}\n{run_log(scratch)}"
    assert unit_state(scratch, FIRST) == str(MERGED), context
    assert unit_state(scratch, SECOND) not in (str(FAILED), str(HELD)), (
        f"the merge broke the dependent{context}"
    )
    # The merge must move the dependent on: a started one is retargeted to main, one not yet
    # started now has its branch.
    assert NEXT_BRANCH in branches(scratch), f"the dependent did not start{context}"
    if before:
        after = forge.list_prs(repo, head_prefix=NEXT_BRANCH)
        assert len(after) == 1, f"the dependent has {len(after)} pull requests{context}"
        assert after[0].base == "main", (
            f"the dependent's pull request still targets {after[0].base}{context}"
        )
    else:
        assert not dependent_started, f"the dependent had a branch but no pull request{context}"
