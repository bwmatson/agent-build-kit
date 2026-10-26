"""A failed unit that has made no commit is requeued onto the base as it is now: after a resume,
a rework, a restart and the automatic requeue when its wait ends, the next run finds its branch
on the moved base (spec: prepare-base).

The worktree is a real git repository and the move is the real one; the requeue is the event the
requeue delivers to the unit's thread, in the mode each one gives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.unit_store import RequeueReason
from agent_build_kit.pipeline.units import FAILED
from tests.empty_branch_support import advance, empty_branch, head, moves
from tests.factories import git
from tests.graph.test_outside_commits_prompt import land
from tests.graph_driver import tick

REQUEUES = {
    "resume": ResumeEvent(kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="resume"),
    "rework": ResumeEvent(
        kind=EventKind.REQUEUE,
        requeue=RequeueReason.FROM_FAILURE,
        reason="rework",
        guidance="try the other way",
    ),
    "restart": ResumeEvent(kind=EventKind.REQUEUE, requeue=RequeueReason.RESTART, reason="restart"),
    "wait end": ResumeEvent(
        kind=EventKind.REQUEUE,
        requeue=RequeueReason.RESUME,
        reason="its wait ended (waiting on base group 1 is now merged)",
    ),
}


@pytest.mark.parametrize("name", list(REQUEUES))
def test_a_failed_unit_with_no_commit_is_requeued_onto_the_moved_base(
    tmp_path: Path, name: str
) -> None:
    recorder, overrides, repo = empty_branch(tmp_path)
    start = head(repo)
    # The first run leaves its thread waiting; the commit is then lost, as a unit that failed
    # before committing never had one.
    land(repo, "Own work", {"src/own.py": "OWN = 1\n"})
    tick(tmp_path, recorder, **overrides)
    git(repo, "reset", "-q", "--hard", start)
    recorder.store.set_state("add-marker/1", FAILED, note="failed before its first commit")
    new = advance(repo)
    recorder.logged.clear()

    tick(tmp_path, recorder, event=REQUEUES[name], **overrides)
    tick(tmp_path, recorder, **overrides)

    assert head(repo) == new
    assert len(moves(recorder)) == 1
