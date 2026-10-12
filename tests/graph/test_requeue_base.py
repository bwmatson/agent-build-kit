"""A requeued unit builds on the base the store names now, not on one its thread remembers,
and a remembered base that no longer resolves gives way to the store's, saying so.

The branch is a real git repository, which the runner's worktree is, and the commits are
counted by the real `branch_commits`: it is the count that raises on a base that is gone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.unit_store import RequeueReason
from agent_build_kit.pipeline.units import FAILED
from agent_build_kit.pipeline.wiring import branch_commits
from tests.factories import git, unit
from tests.graph.test_outside_commits_prompt import branch, drive, land
from tests.graph_driver import tick
from tests.runner_fakes import Recorder

PREDECESSOR = "spec/add-marker/0"
GONE = "spec/add-marker/9"
REQUEUES = {
    "resume": ResumeEvent(kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="again"),
    "rework": ResumeEvent(
        kind=EventKind.REQUEUE,
        requeue=RequeueReason.FROM_FAILURE,
        reason="again",
        guidance="try the other way",
    ),
    "restart": ResumeEvent(kind=EventKind.REQUEUE, requeue=RequeueReason.RESTART, reason="again"),
}


def stacked(tmp_path: Path) -> tuple[Recorder, dict[str, Any], Path]:
    """The unit's branch holds one commit of its own over its predecessor's branch."""
    repo = branch(tmp_path)
    land(repo, "Predecessor", {"src/pred.py": "PRED = 1\n"})
    git(repo, "branch", PREDECESSOR)
    land(repo, "Own work", {"src/own.py": "OWN = 1\n"})
    recorder, _, overrides = drive(tmp_path)
    return recorder, {**overrides, "branch_commits": branch_commits}, repo


def said(recorder: Recorder, text: str) -> bool:
    return any(text in line for line in recorder.logged)


@pytest.mark.parametrize("name", list(REQUEUES))
def test_a_requeue_after_the_predecessor_merged_counts_against_the_trunk(
    tmp_path: Path, name: str
) -> None:
    recorder, overrides, repo = stacked(tmp_path)
    tick(tmp_path, recorder, base=PREDECESSOR, **overrides)
    git(repo, "update-ref", "refs/remotes/origin/main", PREDECESSOR)
    git(repo, "branch", "-D", PREDECESSOR)
    recorder.store.set_state(unit().id, FAILED, note="failed")
    recorder.logged.clear()

    tick(tmp_path, recorder, base="main", event=REQUEUES[name], **overrides)
    tick(tmp_path, recorder, base="main", **overrides)

    assert said(recorder, "on main, 1 commit(s) on the branch")


def test_a_requeued_unit_still_stacked_takes_the_predecessor_the_store_names(
    tmp_path: Path,
) -> None:
    recorder, overrides, _ = stacked(tmp_path)
    tick(tmp_path, recorder, base="main", **overrides)
    recorder.store.set_state(unit().id, FAILED, note="failed")
    recorder.logged.clear()

    tick(tmp_path, recorder, base=PREDECESSOR, event=REQUEUES["resume"], **overrides)
    tick(tmp_path, recorder, base=PREDECESSOR, **overrides)

    assert said(recorder, f"on {PREDECESSOR}, 1 commit(s) on the branch")


def test_a_remembered_base_that_is_gone_falls_back_to_the_stores_and_says_both(
    tmp_path: Path,
) -> None:
    recorder, overrides, _ = stacked(tmp_path)

    def refuses_to_move(**kw: Any) -> None:
        if kw.get("resolve") is False:
            raise RuntimeError("conflict")

    # The base the forge names at the push is a branch that is not there: the unit is sent
    # back to `prepare` remembering it.
    tick(
        tmp_path,
        recorder,
        base="main",
        fresh_base=lambda u, base: GONE,
        restack_onto=refuses_to_move,
        **overrides,
    )

    assert any(
        GONE in line and "main" in line and "no longer exists" in line for line in recorder.logged
    ), recorder.logged
