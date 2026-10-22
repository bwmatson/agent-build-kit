"""A failed unit that waits on a parent resumes after the merge and the next tick has it (spec:
needs-can-wait-for-a-merge): the kind of the `Needs:` and the parent's repository do not matter, in
review never ends the wait, and the history says the merge was loaded and by which tick.

The kit's checkout is a throwaway git repository and each tick's record is written by hand."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.loaded_code import TickRecord, write_record
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, RequeueReason
from agent_build_kit.pipeline.units import CLOSED, FAILED, IN_REVIEW, MERGED, PLANNED
from tests.conftest import run_status
from tests.factories import commit, git, new_unit
from tests.kit_checkout import kit_at
from tests.wait_end_support import CHILD, PARENT, Pipeline, pipeline, save_failure

WAIT_TEXT = (
    "waiting for base group 1 to merge (merge: a failed unit resumes after the fix is merged)"
)


class Kit:
    """The checkout the code is loaded from, with a fix on a branch the head does not have."""

    def __init__(self, pipe: Pipeline, patch: pytest.MonkeyPatch) -> None:
        self.pipe = pipe
        self.path = pipe.inst.checkouts["app"]
        self.head = str(kit_at(self.path, patch))
        git(self.path, "checkout", "-q", "-b", "fix")
        self.fix = commit(self.path, "fix.txt")
        git(self.path, "checkout", "-q", "main")

    def ticks(self, number: int, *, head: str | None = None) -> None:
        """The record tick `number` writes as it starts, with this head (the old one by default)."""
        write_record(
            self.pipe.inst.state_dir,
            TickRecord(
                number=number,
                started_at=datetime.now(UTC),
                kit_repo="app",
                kit_root=str(self.path),
                kit_head=head or self.head,
            ),
        )

    def pull(self) -> str:
        """Fast-forward the checkout onto the fix; the head the next tick reads."""
        git(self.path, "merge", "-q", "--ff-only", "fix")
        return self.fix


@pytest.fixture
def pipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pipeline:
    return pipeline(tmp_path, monkeypatch)


@pytest.fixture
def kit(pipe: Pipeline, monkeypatch: pytest.MonkeyPatch) -> Kit:
    return Kit(pipe, monkeypatch)


def fail_waiting_on(pipe: Pipeline, kind: str) -> None:
    """CHILD failed after an e2e-test and waits on PARENT, which is in review: by an author's
    merge `Needs:`, a plain same-repo one, or a plain one to a group of another repository."""
    parent_repo = "platform" if kind == "cross-repo" else "app"
    pipe.store.upsert([new_unit(PARENT, repo=parent_repo), new_unit(CHILD, depends_on=(PARENT,))])
    pipe.store.set_state(PARENT, IN_REVIEW, pr=1, branch=f"spec/{PARENT}")
    pipe.store.set_needs(CHILD, (PARENT,))
    if kind != "plain":
        pipe.store.set_merge_needs(CHILD, (PARENT,))
    save_failure(pipe, feedback="the check failed", source=FeedbackSource.E2E)


@pytest.mark.parametrize("kind", ["author-merge", "plain", "cross-repo"])
def test_the_wait_ends_at_the_merge_and_the_next_tick_that_has_it(
    pipe: Pipeline, kit: Kit, kind: str
) -> None:
    fail_waiting_on(pipe, kind)
    kit.ticks(3)

    pipe.passes(2)
    assert pipe.store.get(CHILD).state == FAILED, "in review does not end the wait"
    assert pipe.store.get(CHILD).waited_on == (PARENT,)
    assert pipe.host.deliveries == []

    pipe.store.set_state(PARENT, MERGED, pr=1)
    pipe.store.set_merge_record(PARENT, merge_sha=kit.fix, merged_tick=3)
    pipe.passes(2)
    assert pipe.host.deliveries == [], "the tick that saw the merge does not act on it"

    kit.ticks(4, head=kit.pull() if kind != "cross-repo" else None)
    pipe.pass_()
    pipe.pass_()

    [delivery] = pipe.host.deliveries
    assert delivery["unit"] == CHILD
    assert delivery["requeue"] is RequeueReason.FROM_FAILURE, "the mode the existing rule picks"
    assert pipe.store.get(CHILD).waited_on == ()
    assert pipe.wait_ended_notes() == [
        "requeue: its wait ended (waiting on base group 1 is now merged, loaded by tick 4)"
    ]


def test_a_requeue_by_a_person_is_parked_gated_and_released_after_the_merge_is_loaded(
    pipe: Pipeline, kit: Kit
) -> None:
    fail_waiting_on(pipe, "plain")
    kit.ticks(3)
    pipe.pass_()

    assert cli.requeue(pipe.inst, CHILD, "resume", say=lambda *args, **kwargs: None) == 0

    parked = pipe.store.get(CHILD)
    assert (parked.state, parked.cause) == (PLANNED, Cause.GATED)
    assert WAIT_TEXT in parked.note

    pipe.store.set_state(PARENT, MERGED, pr=1)
    pipe.store.set_merge_record(PARENT, merge_sha=kit.fix, merged_tick=3)
    cli.release_gated(pipe.inst, pipe.store)
    assert pipe.host.deliveries == [], "merged, but not in the code this tick runs"

    kit.ticks(4, head=kit.pull())
    cli.release_gated(pipe.inst, pipe.store)

    [delivery] = pipe.host.deliveries
    assert delivery["requeue"] is RequeueReason.RESUME
    pipe.pass_()
    assert pipe.store.get(CHILD).waited_on == ()
    assert len(pipe.host.deliveries) == 1


def test_a_closed_merge_parent_leaves_the_unit_failed_and_says_so(
    pipe: Pipeline,
    kit: Kit,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fail_waiting_on(pipe, "author-merge")
    kit.ticks(3)
    pipe.pass_()
    lines = run_status(pipe.inst, monkeypatch, capsys)
    assert any(
        "failed, waiting on" in line
        and "waiting for base group 1 to merge (merge: the Needs: line says merged)" in line
        for line in lines
    )

    pipe.store.set_state(PARENT, CLOSED)
    pipe.passes(2)

    after = pipe.store.get(CHILD)
    assert after.state == FAILED
    assert after.wait_ended == "base group 1"
    assert after.waited_on == ()
    assert pipe.host.deliveries == []
