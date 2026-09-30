"""What the pipeline does when GitHub tells it something changed.

`pr_poller` notices; this decides. Until these handlers existed nothing moved
past `open`: a merged PR left its unit sitting there and its children stacked
on a branch that no longer needed to exist.

The one that carries real weight is **merged**. Merging the bottom of a stack
changes what every branch above it should sit on, and getting that wrong is
how a child PR starts showing its parent's diff as its own — or worse, how a
force-push lands commits nobody reviewed on a base that already has them.
"""

from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest, ReviewNote
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON, Poller
from agent_build_kit.pipeline.restack import Moved, RestackConflict, StaleRemote
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import CLOSED, IN_REVIEW, MERGED, PLANNED, RUNNING, SATISFIED
from agent_build_kit.pipeline.usage_guard import Interrupted, RateLimited
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import stored_unit as unit


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    """A two-unit stack: add-marker/2 sits on add-marker/1, both open."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1"), unit("add-marker/2", depends_on=("add-marker/1",))])
    store.set_state("add-marker/1", IN_REVIEW, pr=1, branch="spec/add-marker/1")
    store.set_state("add-marker/2", IN_REVIEW, pr=2, branch="spec/add-marker/2")
    return store


class Recorder:
    def __init__(self) -> None:
        self.restacked: list[dict] = []

    def __call__(self, **kwargs) -> None:
        self.restacked.append(kwargs)


def test_a_merged_pr_marks_its_unit_merged(store: UnitStore) -> None:
    events.on_merged(1, repo="app", store=store, restack=Recorder())

    assert store.get("add-marker/1").state == MERGED


def test_merging_the_bottom_restacks_what_was_on_top(store: UnitStore) -> None:
    """The child's branch still sits on its parent's, which main now contains.
    Left alone, its PR shows both units' work as its own diff."""
    recorder = Recorder()

    events.on_merged(1, repo="app", store=store, restack=recorder)

    assert len(recorder.restacked) == 1
    moved = recorder.restacked[0]
    assert moved["branch"] == "spec/add-marker/2"
    assert moved["old_base"] == "spec/add-marker/1"
    assert moved["new_base"] == "main", "its only open parent just merged"


def test_a_child_moves_onto_its_next_open_parent_not_main(tmp_path: Path) -> None:
    """Three deep: merging the bottom leaves the top sitting on the middle,
    which is still open. Sending it to main would drop the middle's work from
    under it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("c/1"),
            unit("c/2", depends_on=("c/1",)),
            unit("c/3", depends_on=("c/1", "c/2")),
        ]
    )
    for n in (1, 2, 3):
        store.set_state(f"c/{n}", IN_REVIEW, pr=n, branch=f"spec/c/{n}")
    recorder = Recorder()

    events.on_merged(1, repo="app", store=store, restack=recorder)

    moved = {r["branch"]: r["new_base"] for r in recorder.restacked}
    assert moved["spec/c/2"] == "main"
    assert moved["spec/c/3"] == "spec/c/2", "still stacked on the open middle"


def test_a_grandchild_through_a_satisfied_unit_is_restacked_like_a_direct_child(
    tmp_path: Path,
) -> None:
    """Unit 2 added nothing of its own and was judged satisfied on unit 1's
    branch, so unit 3 — which depends on unit 2 — was actually built directly
    on unit 1's branch (`base_of` looks straight through a satisfied unit).
    When unit 1 merges, unit 3 is a grandchild through unit 2 and has to move
    exactly as a direct child would; finding only unit 2 as the child would
    leave unit 3 sitting on a branch about to be deleted."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("c/1"),
            unit("c/2", depends_on=("c/1",)),
            unit("c/3", depends_on=("c/2",)),
        ]
    )
    store.set_state("c/1", IN_REVIEW, pr=1, branch="spec/c/1")
    store.set_state("c/2", "satisfied")
    store.set_state("c/3", IN_REVIEW, pr=3, branch="spec/c/3")
    recorder = Recorder()

    events.on_merged(1, repo="app", store=store, restack=recorder)

    assert len(recorder.restacked) == 1
    moved = recorder.restacked[0]
    assert moved["branch"] == "spec/c/3"
    assert moved["old_base"] == "spec/c/1"
    assert moved["new_base"] == "main"
    assert moved["parent"].id == "c/1"


def test_a_merge_we_have_no_unit_for_is_ignored(store: UnitStore) -> None:
    """Someone else's PR on a spec/ branch, or a unit removed from the store.
    Restacking against a unit we don't know is how the wrong branch moves."""
    recorder = Recorder()

    events.on_merged(999, repo="app", store=store, restack=recorder)

    assert recorder.restacked == []


def test_a_failing_restack_does_not_stop_the_others(tmp_path: Path) -> None:
    """One conflicted child is left for a human; the rest of the stack still
    gets moved, or a single conflict freezes everything above it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1"), unit("c/2", depends_on=("c/1",)), unit("c/3", depends_on=("c/1",))])
    for n in (1, 2, 3):
        store.set_state(f"c/{n}", IN_REVIEW, pr=n, branch=f"spec/c/{n}")
    moved: list[str] = []

    def restack(*, branch, **kwargs):
        if branch == "spec/c/2":
            raise RuntimeError("conflict")
        moved.append(branch)

    events.on_merged(1, repo="app", store=store, restack=restack)

    assert moved == ["spec/c/3"]
    assert store.get("c/1").state == MERGED, "the merge itself still stands"


def test_a_closed_pr_marks_its_unit_closed(store: UnitStore) -> None:
    events.on_closed(1, repo="app", store=store)

    assert store.get("add-marker/1").state == CLOSED


def test_closing_a_parent_leaves_its_children_alone(store: UnitStore) -> None:
    """Closing is a human decision about one unit. Cascading it would discard
    work on branches nobody asked to drop."""
    events.on_closed(1, repo="app", store=store)

    assert store.get("add-marker/2").state == IN_REVIEW


def test_rework_is_recorded_against_the_unit(store: UnitStore) -> None:
    """The reason has to survive the poll: the next tick is a new process, and
    rebuilding without knowing what the reviewer said would reproduce the same
    code at full price."""
    events.on_rework(1, repo="app", reason="new comment", store=store)

    assert "new comment" in str(store.get("add-marker/1").history[-1])


def test_a_held_unit_is_recorded_so_nothing_reworks_it(store: UnitStore) -> None:
    events.on_hold(1, repo="app", store=store)

    assert store.get("add-marker/1").state == events.HELD


def test_a_satisfied_units_own_close_is_not_read_back_as_a_real_one(store: UnitStore) -> None:
    """`wiring.build_close_pr` posts the reason and closes a satisfied unit's
    stale pull request itself — the same OPEN→CLOSED transition a human's
    close would make. Recording that here would turn SATISFIED into CLOSED,
    which blocks archiving, leaves dependents waiting forever (CLOSED is not
    in `REVIEWED`) and stops `through_satisfied` looking through it."""
    store.set_state("add-marker/1", SATISFIED, pr=4)

    events.on_closed(4, repo="app", store=store)

    assert store.get("add-marker/1").state == SATISFIED


def test_a_satisfied_unit_is_not_reworked_by_a_late_comment(store: UnitStore) -> None:
    store.set_state("add-marker/1", SATISFIED, pr=4)

    events.on_rework(4, repo="app", reason="new comment", store=store)

    assert store.get("add-marker/1").state == SATISFIED


def test_a_satisfied_unit_is_not_held_by_a_late_review(store: UnitStore) -> None:
    store.set_state("add-marker/1", SATISFIED, pr=4)

    events.on_hold(4, repo="app", store=store)

    assert store.get("add-marker/1").state == SATISFIED


def test_a_restack_reruns_the_checks_before_it_pushes(tmp_path: Path) -> None:
    """The move rewrites every commit on the branch. Pushing first would put a
    head nobody has verified in front of a reviewer, with the old green tick
    still showing beside it."""
    order: list[str] = []
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: order.append("move") or Moved(sha="newsha"),
        tier1=lambda **k: (order.append("tier1"), (True, ""))[1],
        push=lambda *a, **k: order.append("push") or "newsha",
        retarget=lambda *a, **k: order.append("retarget"),
        comment=lambda *a, **k: order.append("comment"),
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )

    restack(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=unit("c/2", pr=2, branch="spec/c/2", approved="approved"),
        parent=unit("c/1", pr=1, branch="spec/c/1"),
    )

    assert order == ["retarget", "move", "tier1", "push", "comment"]


def test_a_restack_that_breaks_the_branch_is_not_pushed(tmp_path: Path) -> None:
    """A conflict resolved wrongly compiles and fails. Pushing it would replace
    a reviewable branch with a broken one."""
    pushed: list[str] = []
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: Moved(sha="newsha"),
        tier1=lambda **k: (False, "boom"),
        push=lambda *a, **k: pushed.append("pushed") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )

    with pytest.raises(RuntimeError, match="checks fail"):
        restack(
            branch="spec/c/2",
            old_base="spec/c/1",
            new_base="main",
            child=unit("c/2", pr=2, branch="spec/c/2", approved="approved"),
            parent=unit("c/1", pr=1, branch="spec/c/1"),
        )

    assert pushed == []


def test_the_comment_says_what_moved_underneath_the_reviewer(tmp_path: Path) -> None:
    """A force-push with no explanation reads as the agent rewriting history."""
    posted: list[str] = []
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: Moved(sha="newsha"),
        tier1=lambda **k: (True, ""),
        push=lambda *a, **k: "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda pr, body, **k: posted.append(body),
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )

    restack(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=unit("c/2", pr=2, branch="spec/c/2", approved="approved"),
        parent=unit("c/1", pr=1, branch="spec/c/1"),
    )

    assert "spec/c/1" in posted[0] and "main" in posted[0]


def _restack_with(tmp_path: Path, store: UnitStore, pushed: list[str], *, after: str, head: str):
    diffs = iter(["before-diff", after])
    return events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: Moved(sha="newsha"),
        tier1=lambda **k: (True, ""),
        push=lambda *a, **k: pushed.append("pushed") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: next(diffs),
        head_of=lambda repo, branch: head,
    )


def test_a_restack_that_changed_the_diff_goes_back_to_review_not_to_the_pr(
    tmp_path: Path,
) -> None:
    """A conflict the resolver rewrote is code no review has seen. It is
    reviewed first, and the runner pushes once it passes."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    pushed: list[str] = []

    _restack_with(tmp_path, store, pushed, after="different-diff", head="approved")(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=unit("c/2", pr=2, branch="spec/c/2", approved="approved"),
        parent=unit("c/1", pr=1, branch="spec/c/1"),
    )

    assert pushed == []
    assert store.get("c/2").state == PLANNED
    assert store.get("c/2").resume_from == "rework_review"


def test_a_head_review_never_approved_is_not_pushed_by_a_restack(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    pushed: list[str] = []

    _restack_with(tmp_path, store, pushed, after="before-diff", head="something-else")(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=unit("c/2", pr=2, branch="spec/c/2", approved="approved"),
        parent=unit("c/1", pr=1, branch="spec/c/1"),
    )

    assert pushed == []


def test_a_clean_restack_carries_the_approval_to_the_new_head(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    pushed: list[str] = []
    heads = iter(["approved", "rebased-head"])
    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: Moved(sha="newsha"),
        tier1=lambda **k: (True, ""),
        push=lambda *a, **k: pushed.append("pushed") or "rebased-head",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: next(heads),
    )

    restack(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=unit("c/2", pr=2, branch="spec/c/2", approved="approved"),
        parent=unit("c/1", pr=1, branch="spec/c/1"),
    )

    assert pushed == ["pushed"]
    assert store.get("c/2").approved == "rebased-head"


def test_a_branch_the_host_moved_is_re_reviewed_before_anything_is_pushed(
    tmp_path: Path,
) -> None:
    """After a stack merge the host rebases the pull requests above and
    force-pushes their branches itself. No run of the unit moved it, so the
    local branch still sits at the approved commit — only the branch on the
    host says otherwise, and that is what has to be inspected. The old
    approval does not carry to a head review never saw."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    store.set_state("c/2", IN_REVIEW, pr=2, branch="spec/c/2")
    store.record_approval("c/2", "approved")
    store.record_push("c/2", "approved")
    order: list[str] = []
    adopted: list[dict] = []
    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: order.append("move") or Moved(sha="newsha"),
        tier1=lambda **k: (order.append("tier1"), (True, ""))[1],
        push=lambda *a, **k: order.append("push") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
        remote_head_of=lambda repo, branch: "host-rebased",
        adopt=lambda repo, branch, **k: order.append("adopt") or adopted.append(k) or "",
    )

    restack(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=store.get("c/2"),
        parent=unit("c/1", pr=1, branch="spec/c/1", state=MERGED),
    )

    assert "push" not in order
    # The host already rebased it onto the trunk: `old_base..branch` now spans
    # trunk commits that are not the unit's, and replaying them invites
    # conflicts in code it never touched.
    assert "move" not in order, "a branch the host rebased is not moved again"
    assert adopted[0]["host_head"] == "host-rebased"
    assert store.get("c/2").state == PLANNED
    assert store.get("c/2").resume_from == "rework_review"
    assert store.get("c/2").approved == "", "no approval for the host's head"
    assert store.get("c/2").pushed == "host-rebased", "the next lease names what the host has"


def test_a_failed_adopt_still_retargets_the_pr(tmp_path: Path) -> None:
    """With its base merged away, a PR left pointing at it is closed by the
    host. Whatever adopting the host's head does, the retarget has happened."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    store.set_state("c/2", IN_REVIEW, pr=2, branch="spec/c/2")
    store.record_push("c/2", "approved")
    retargeted: list[tuple] = []

    def adopt(*a, **k):
        raise StaleRemote("local commits do not apply")

    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: Moved(sha="newsha"),
        tier1=lambda **k: (True, ""),
        push=lambda *a, **k: "newsha",
        retarget=lambda pr, base, **k: retargeted.append((pr, base)),
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
        remote_head_of=lambda repo, branch: "host-rebased",
        adopt=adopt,
    )

    with pytest.raises(StaleRemote):
        restack(
            branch="spec/c/2",
            old_base="spec/c/1",
            new_base="main",
            child=store.get("c/2"),
            parent=unit("c/1", pr=1, branch="spec/c/1", state=MERGED),
        )

    assert retargeted == [(2, "main")]


def test_a_push_whose_recording_was_lost_is_not_taken_for_a_host_move(tmp_path: Path) -> None:
    """A crash between a push and recording it leaves the host ahead of the
    store but level with the local branch. Nobody moved it, so the approval
    stands and the restack goes ahead as usual."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    store.set_state("c/2", IN_REVIEW, pr=2, branch="spec/c/2")
    store.record_approval("c/2", "approved")
    store.record_push("c/2", "before")
    leases: list[str | None] = []
    heads = iter(["approved", "approved", "rebased-head"])
    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: Moved(sha="newsha"),
        tier1=lambda **k: (True, ""),
        push=lambda repo, branch, last_pushed: leases.append(last_pushed) or "rebased-head",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: next(heads),
        remote_head_of=lambda repo, branch: "approved",
        adopt=lambda *a, **k: pytest.fail("nothing to adopt"),
    )

    restack(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=store.get("c/2"),
        parent=unit("c/1", pr=1, branch="spec/c/1", state=MERGED),
    )

    assert leases == ["approved"], "the lease names what the host really has"
    assert store.get("c/2").approved == "rebased-head"


def test_the_poller_s_events_reach_the_handlers(tmp_path: Path) -> None:
    """The names in the dispatch table are the poller's contract; a typo here
    is an event that silently does nothing."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1")])
    store.set_state("c/1", IN_REVIEW, pr=1, branch="spec/c/1")
    dispatch = events.build_dispatch(store, restack=Recorder(), log=lambda m: None)

    dispatch("merged", 1, repo="app")

    assert store.get("c/1").state == MERGED


def test_an_unknown_event_is_logged_rather_than_ignored(tmp_path: Path) -> None:
    """If the poller grows an event this doesn't handle, the silence would
    look exactly like a working pipeline with nothing to do."""
    store = UnitStore(tmp_path / "units.json")
    logged: list[str] = []
    dispatch = events.build_dispatch(store, restack=Recorder(), log=logged.append)

    dispatch("something-new", 1, repo="app")

    assert any("something-new" in line for line in logged)


def rework_pull(body: str) -> PullRequest:
    return PullRequest(
        number=1,
        head="spec/add-marker/1",
        base="main",
        state="open",
        conversation=("c1",),
        comment_bodies=(body,),
    )


def bare_pull() -> PullRequest:
    """A PR with nothing said on it: a failing check dispatches rework too."""
    return PullRequest(number=1, head="spec/add-marker/1", base="main", state="open")


def test_rework_keeps_what_the_reviewer_actually_said(store: UnitStore) -> None:
    """ "new comment" is not actionable. Rebuilding on that alone would spend a
    full unit's budget reproducing the same code, so the text is the point."""
    events.on_rework(
        1, repo="app", reason="new comment", pull=rework_pull("Use a Sequence here"), store=store
    )

    assert store.get("add-marker/1").feedback == "Use a Sequence here"


def test_a_reworked_unit_goes_back_in_the_queue(store: UnitStore) -> None:
    """Recording it and leaving the unit open would mean the feedback sat
    there until someone noticed by hand."""
    events.on_rework(
        1, repo="app", reason="new comment", pull=rework_pull("Use a Sequence"), store=store
    )

    assert store.get("add-marker/1").state == PLANNED


def test_feedback_with_no_comment_still_says_why(store: UnitStore) -> None:
    """A failing check dispatches rework too, and its reason is all there is."""
    events.on_rework(1, repo="app", reason="failing checks: tier1", pull=bare_pull(), store=store)

    assert "failing checks: tier1" in store.get("add-marker/1").feedback


def test_a_held_unit_is_not_requeued_by_a_comment(store: UnitStore) -> None:
    """Hold means a human has taken it over. Requeuing would have the agent
    push over the work they are in the middle of."""
    events.on_hold(1, repo="app", store=store)

    events.on_rework(
        1, repo="app", reason="new comment", pull=rework_pull("thoughts?"), store=store
    )

    assert store.get("add-marker/1").state == events.HELD
    assert store.get("add-marker/1").feedback == ""


def test_a_merged_unit_s_worktree_is_removed(store: UnitStore) -> None:
    """Nothing else ever removes one. Left alone they accumulate a full
    checkout per unit — app already carries nine from earlier runs — and
    every one of them is a working tree git has to keep track of."""
    removed: list[str] = []

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Recorder(),
        remove_worktree=lambda repo, branch: removed.append(branch),
    )

    assert removed == ["spec/add-marker/1"]


def test_a_worktree_that_will_not_go_does_not_fail_the_merge(store: UnitStore) -> None:
    """`remove_worktree` refuses a dirty tree on purpose, since uncommitted
    work there may be the only copy. The merge itself already happened, so
    that has to be a log line and not an exception."""

    def refuse(repo, branch):
        raise RuntimeError("worktree has uncommitted changes")

    events.on_merged(1, repo="app", store=store, restack=Recorder(), remove_worktree=refuse)

    assert store.get("add-marker/1").state == MERGED


def test_a_child_s_worktree_survives_the_parent_merge(tmp_path: Path) -> None:
    """Only the merged unit is finished. A child still has an open PR and may
    yet be restacked or reworked in its own tree."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1"), unit("c/2", depends_on=("c/1",))])
    for n in (1, 2):
        store.set_state(f"c/{n}", IN_REVIEW, pr=n, branch=f"spec/c/{n}")
    removed: list[str] = []

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Recorder(),
        remove_worktree=lambda repo, branch: removed.append(branch),
    )

    assert removed == ["spec/c/1"]


def test_a_merged_unit_s_branch_is_deleted(store: UnitStore) -> None:
    """Otherwise one stale local branch accumulates per unit, forever. The
    remote side is already handled — GitHub deletes the head branch on merge."""
    deleted: list[str] = []

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Recorder(),
        remove_worktree=lambda repo, branch: None,
        delete_branch=lambda repo, branch: deleted.append(branch),
    )

    assert deleted == ["spec/add-marker/1"]


def test_the_branch_goes_only_after_its_worktree(store: UnitStore) -> None:
    """A branch checked out in a worktree cannot be deleted, so the order is
    not a preference."""
    order: list[str] = []

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Recorder(),
        remove_worktree=lambda repo, branch: order.append("worktree"),
        delete_branch=lambda repo, branch: order.append("branch"),
    )

    assert order == ["worktree", "branch"]


def test_a_kept_worktree_keeps_its_branch(store: UnitStore) -> None:
    """`remove_worktree` refuses a dirty tree because what is in it may be the
    only copy. Deleting the branch anyway would strand that work on a detached
    checkout with no ref pointing at it."""
    deleted: list[str] = []

    def refuse(repo, branch):
        raise RuntimeError("worktree has uncommitted changes")

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Recorder(),
        remove_worktree=refuse,
        delete_branch=lambda repo, branch: deleted.append(branch),
    )

    assert deleted == []
    assert store.get("add-marker/1").state == MERGED


def test_a_closed_unmerged_unit_keeps_its_branch(store: UnitStore) -> None:
    """Closed is not merged: the branch is the only place that work exists,
    and dropping a PR is not a decision to destroy what was on it."""
    events.on_closed(1, repo="app", store=store)

    assert store.get("add-marker/1").state == CLOSED


def test_rework_carries_the_reviewer_s_inline_words(store: UnitStore) -> None:
    """A review's bodies can be empty with the whole content one inline
    comment on a line — which `gh pr list` does not return at
    all. Feedback saying only "changes requested" is the uselessness the rework
    path exists to avoid, so the words are fetched when they are needed."""
    events.on_rework(
        1,
        repo="app",
        reason="review: changes requested",
        pull=bare_pull(),
        store=store,
        fetch_review=lambda number: [
            "shared/tests/test_x.py:28 — This should be a StrEnum so it can be used as keys."
        ],
    )

    feedback = store.get("add-marker/1").feedback
    assert "StrEnum" in feedback
    assert "test_x.py:28" in feedback


def test_rework_falls_back_to_the_reason_when_there_are_no_words(store: UnitStore) -> None:
    """A failing check dispatches rework too and has no review behind it."""
    events.on_rework(
        1,
        repo="app",
        reason="failing checks: tier1",
        pull=bare_pull(),
        store=store,
        fetch_review=lambda number: [],
    )

    assert "failing checks: tier1" in store.get("add-marker/1").feedback


def test_outdated_review_comments_are_not_replayed(store: UnitStore) -> None:
    """A note the host reports as no longer live — GitHub sets `line: null`
    once the code has changed, Azure DevOps resolves the thread — is, after a
    rework, exactly the note that rework addressed. Sending it again tells the
    agent to redo work it has done, and every later round would carry every
    earlier note."""
    fetched = events.review_lines(
        [
            ReviewNote(id="28", body="make it a StrEnum", path="a.py", line=None, live=False),
            ReviewNote(id="35", body="drop the redundant value", path="a.py", line=35),
        ]
    )

    assert fetched == ["[comment 35] a.py:35 — drop the redundant value"]


def test_a_review_body_is_never_outdated(store: UnitStore) -> None:
    """Only inline comments are anchored to a line, so a submitted review's own
    body has nothing to go stale against."""
    lines = events.review_lines([ReviewNote(id="1", body="please split this")])

    assert lines == ["please split this"]


def test_inline_comments_carry_their_id_so_replies_can_find_the_thread() -> None:
    lines = events.review_lines([ReviewNote(id="11", path="a.py", line=3, body="rename")])

    assert lines == ["[comment 11] a.py:3 — rename"]


def test_the_pipeline_s_own_replies_are_not_read_back_as_review() -> None:
    """Otherwise the next rework would be asked to respond to itself."""
    from agent_build_kit.pipeline.pr_replies import MARKER

    lines = events.review_lines(
        [
            ReviewNote(id="1", body=f"summary of the rework\n{MARKER}"),
            ReviewNote(id="11", path="a.py", line=3, body="rename"),
            ReviewNote(id="12", path="a.py", line=3, body=f"Renamed.\n{MARKER}"),
        ]
    )

    assert lines == ["[comment 11] a.py:3 — rename"]


def test_new_feedback_overrides_where_a_paused_unit_would_resume(tmp_path: Path) -> None:
    """Resuming at a review would skip the rework the feedback asks for, and a
    pass would then clear that feedback unread."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", PLANNED, pr=1, resume_from="review")

    events.on_rework(1, repo="app", store=store, reason="new comment", log=lambda m: None)

    assert store.get("add-marker/1").resume_from == ""


def test_a_clean_rebase_keeps_the_diff_id_and_a_changed_diff_does_not(tmp_path: Path) -> None:
    """What lets a restack push without a second review: the id is the same
    exactly when the unit's own change is."""
    from agent_build_kit.pipeline import restack
    from tests.factories import git, init_repo

    repo = init_repo(tmp_path / "r")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-q", "-b", "unit")
    (repo / "unit.txt").write_text("the unit's change\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unit")
    before = restack.diff_id(repo, "main", "unit")

    git(repo, "checkout", "-q", "main")
    (repo / "other.txt").write_text("the parent's merged work\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "parent")
    git(repo, "rebase", "-q", "main", "unit")

    assert restack.diff_id(repo, "main", "unit") == before

    (repo / "unit.txt").write_text("resolved differently\n")
    git(repo, "commit", "-qam", "resolution")
    assert restack.diff_id(repo, "main", "unit") != before


def test_a_rework_is_not_handed_the_pipeline_s_own_comment(tmp_path: Path) -> None:
    """The newest PR comment is usually the reviewer's — unless it is the
    pipeline's summary of its last rework, which is not review."""
    from agent_build_kit.pipeline.pr_replies import MARKER

    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1")])
    store.set_state("c/1", IN_REVIEW, pr=1, branch="spec/c/1")
    pull = rework_pull("please rename it").model_copy(
        update={"comment_bodies": ("please rename it", f"Renamed.\n{MARKER}")}
    )

    events.on_rework(
        1, repo="app", store=store, reason="new comment", pull=pull, log=lambda m: None
    )

    feedback = store.get("c/1").feedback
    assert "please rename it" in feedback
    assert "Renamed." not in feedback


def test_a_restack_that_cannot_be_merged_goes_to_the_adapt_step_not_a_human(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    store.set_state("c/2", IN_REVIEW, pr=2, branch="spec/c/2")
    pushed: list[str] = []
    retargeted: list[str] = []

    def conflicts(*a, **k):
        raise RestackConflict("the resolution dropped a test")

    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=conflicts,
        tier1=lambda **k: (True, ""),
        push=lambda *a, **k: pushed.append("pushed") or "x",
        retarget=lambda pr, base, **k: retargeted.append(base),
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "d",
        head_of=lambda repo, branch: "h",
    )

    restack(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=unit("c/2", pr=2, branch="spec/c/2", approved="h"),
        parent=unit("c/1", pr=1, branch="spec/c/1"),
    )

    assert pushed == []
    assert retargeted == ["main"], "retargeted anyway, so GitHub does not close the PR"
    assert store.get("c/2").state == PLANNED


@pytest.mark.parametrize(
    ("refusal", "why"),
    [
        (RateLimited("usage limit reached", resets_at=None), "rate limit"),
        (Interrupted("claude was killed by signal 15"), "interrupted"),
    ],
    ids=["rate-limited", "interrupted"],
)
def test_a_restack_the_resolver_could_not_run_is_deferred_to_the_runner(
    tmp_path: Path, refusal: Exception, why: str
) -> None:
    """Not lost: the merge event is handled once, and the merged parent's
    branch is deleted next, so a child left `in_review` would never move.
    Planned again, the runner's own restack retries it — and pauses the tick
    if the window is still spent."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    store.set_state("c/2", IN_REVIEW, pr=2, branch="spec/c/2")
    sent: list[str] = []

    def refused(*a, **k):
        raise refusal

    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=refused,
        tier1=lambda **k: (True, ""),
        push=lambda *a, **k: sent.append("pushed") or "x",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: sent.append("commented"),
        diff_id=lambda repo, base, branch: "d",
        head_of=lambda repo, branch: "h",
    )

    restack(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=unit("c/2", pr=2, branch="spec/c/2", approved="h"),
        parent=unit("c/1", pr=1, branch="spec/c/1"),
    )

    assert sent == []
    assert store.get("c/2").state == PLANNED
    note = store.get("c/2").history[-1]["note"]
    assert "deferred" in note
    assert why in note


def test_a_restack_the_resolver_rewrote_tells_the_reviewer_to_check_the_tests(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/2")])
    pushed: list[str] = []
    restack = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=lambda *a, **k: Moved(sha="new", resolved=("src/mcp.py",)),
        tier1=lambda **k: (True, ""),
        push=lambda *a, **k: pushed.append("pushed") or "new",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same",
        head_of=lambda repo, branch: "approved",
    )

    restack(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=unit("c/2", pr=2, branch="spec/c/2", approved="approved"),
        parent=unit("c/1", pr=1, branch="spec/c/1"),
    )

    assert pushed == [], "even an unchanged diff id does not excuse a resolver's edit"
    assert "src/mcp.py" in store.get("c/2").predecessor_note
    assert store.get("c/2").resume_from == "rework_review"


def test_a_ci_failure_is_reworked_from_its_log_not_the_old_review(tmp_path: Path) -> None:
    """The rework got only "failing checks: <name>" — and replayed the PR's
    already-answered review comments besides."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1")])
    store.set_state("c/1", IN_REVIEW, pr=20, branch="spec/c/1")

    events.on_rework(
        20,
        repo="app",
        reason="failing checks: config-check",
        pull=rework_pull("an old, answered review comment"),
        store=store,
        fetch_review=lambda pr: ["an old review"],
        fetch_checks=lambda pull: "AssertionError: container names left on profiled services",
        log=lambda m: None,
    )

    feedback = store.get("c/1").feedback
    assert "config-check" in feedback
    assert "container names left" in feedback
    assert "old" not in feedback


def test_a_conflict_is_reworked_as_a_conflict_not_the_old_review(tmp_path: Path) -> None:
    """A conflict took the reviewer's path, so the rework was handed the PR's
    already-answered review and comment and never told the branch conflicts."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1")])
    store.set_state("c/1", IN_REVIEW, pr=20, branch="spec/c/1")
    asked: list[int] = []

    events.on_rework(
        20,
        repo="app",
        reason=CONFLICT_REASON,
        pull=rework_pull("an old, answered comment"),
        store=store,
        fetch_review=lambda pr: asked.append(pr) or ["an old review body"],
        log=lambda m: None,
    )

    feedback = store.get("c/1").feedback
    assert "conflict" in feedback
    assert "old" not in feedback
    assert "rebase onto" not in feedback
    assert asked == []
    assert store.get("c/1").state == PLANNED


def test_the_github_log_constants_are_not_defined_here() -> None:
    from agent_build_kit.pipeline import events

    for name in ("RUN_URL", "LOG_PREFIX", "CHECK_LOG_CHARS"):
        assert not hasattr(events, name), f"{name} belongs to the GitHub forge, if anywhere"


# --- a unit being built is left alone ----------------------------------------------
#
# A pass polls between builds, so an event can name a unit whose build still
# holds its branch lock. Acting then would rebase the tree the agent is
# writing to, or be overwritten when the build records how it ended.


@pytest.fixture
def locks(tmp_path: Path) -> Path:
    return tmp_path / "locks"


def test_a_merge_does_not_restack_a_child_that_is_being_built(
    store: UnitStore, locks: Path
) -> None:
    """The merge itself stands and the child's PR is pointed at its new base,
    which touches no tree; its branch is left for its build, which stops on
    seeing its base moved."""
    store.set_state("add-marker/2", RUNNING)
    recorder = Recorder()
    retargeted: list[tuple[str, str]] = []

    with branch_lock("spec/add-marker/2", root=locks):
        handled = events.on_merged(
            1,
            repo="app",
            store=store,
            restack=recorder,
            claim=events.build_claim(locks),
            retarget=lambda child, base: retargeted.append((child.id, base)),
            log=lambda m: None,
        )

    assert handled
    assert recorder.restacked == []
    assert store.get("add-marker/1").state == MERGED
    assert store.get("add-marker/2").state == RUNNING
    assert retargeted == [("add-marker/2", "main")]


def test_a_merge_keeps_the_parent_branch_a_child_is_building_on(
    store: UnitStore, locks: Path
) -> None:
    """The child's build started on the parent's local branch and keeps
    diffing against it until its next step holds it. Deleted under it, the
    build counts no commits of its own and fails instead of being held."""
    store.set_state("add-marker/2", RUNNING)
    removed: list[tuple[str, str]] = []
    deleted: list[tuple[str, str]] = []

    with branch_lock("spec/add-marker/2", root=locks):
        events.on_merged(
            1,
            repo="app",
            store=store,
            restack=Recorder(),
            remove_worktree=lambda repo, branch: removed.append((repo, branch)),
            delete_branch=lambda repo, branch: deleted.append((repo, branch)),
            claim=events.build_claim(locks),
            log=lambda m: None,
        )

    assert removed == [("app", "spec/add-marker/1")], "the parent's own tree still goes"
    assert deleted == []


def test_a_merge_keeps_the_parent_branch_a_starting_build_has_taken_as_base(
    store: UnitStore, locks: Path
) -> None:
    """A build holds its lock and fixes its base ref while the unit is still
    `planned` — it only writes `running` later. Deleted then, a first build
    cannot create its worktree and a resume counts no commits of its own."""
    store.set_state("add-marker/2", PLANNED)
    recorder = Recorder()
    removed: list[tuple[str, str]] = []
    deleted: list[tuple[str, str]] = []

    with branch_lock("spec/add-marker/2", root=locks):
        events.on_merged(
            1,
            repo="app",
            store=store,
            restack=recorder,
            remove_worktree=lambda repo, branch: removed.append((repo, branch)),
            delete_branch=lambda repo, branch: deleted.append((repo, branch)),
            claim=events.build_claim(locks),
            log=lambda m: None,
        )

    assert deleted == []
    assert recorder.restacked == [], "its own resume restacks it"
    assert removed == [("app", "spec/add-marker/1")]
    assert store.get("add-marker/2").state == PLANNED


def test_a_merge_restacks_a_child_nothing_is_building(store: UnitStore, locks: Path) -> None:
    recorder = Recorder()
    deleted: list[tuple[str, str]] = []

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=recorder,
        delete_branch=lambda repo, branch: deleted.append((repo, branch)),
        claim=events.build_claim(locks),
    )

    assert [moved["branch"] for moved in recorder.restacked] == ["spec/add-marker/2"]
    assert deleted == [("app", "spec/add-marker/1")]
    assert not list(locks.glob("*.lock")), "the handler's own hold is released"


def test_a_merge_over_a_rework_in_progress_waits_for_the_build(
    store: UnitStore, locks: Path
) -> None:
    """Someone merged a PR its unit is still reworking. Recorded now, the
    build's own `in_review` at the end would overwrite `merged`."""
    store.set_state("add-marker/1", RUNNING)
    recorder = Recorder()

    with branch_lock("spec/add-marker/1", root=locks):
        handled = events.on_merged(
            1,
            repo="app",
            store=store,
            restack=recorder,
            claim=events.build_claim(locks),
            log=lambda m: None,
        )

    assert handled is False, "deferred, so the poller reports it again"
    assert store.get("add-marker/1").state == RUNNING
    assert recorder.restacked == []


@pytest.mark.parametrize(
    "handle",
    [
        lambda store, claim: events.on_rework(
            1, repo="app", reason="new comment", store=store, claim=claim, log=lambda m: None
        ),
        lambda store, claim: events.on_hold(
            1, repo="app", store=store, claim=claim, log=lambda m: None
        ),
        lambda store, claim: events.on_closed(
            1, repo="app", store=store, claim=claim, log=lambda m: None
        ),
    ],
    ids=["rework", "hold", "closed"],
)
def test_an_event_for_a_unit_being_built_changes_nothing(
    store: UnitStore, locks: Path, handle
) -> None:
    store.set_state("add-marker/1", RUNNING)
    store.set_feedback("add-marker/1", "what the build is addressing")

    with branch_lock("spec/add-marker/1", root=locks):
        handled = handle(store, events.build_claim(locks))

    assert handled is False
    after = store.get("add-marker/1")
    assert (after.state, after.feedback) == (RUNNING, "what the build is addressing")


def _pull(**overrides) -> PullRequest:
    fields: dict = {
        "number": 1,
        "head": "spec/add-marker/1",
        "base": "main",
        "state": "open",
        **overrides,
    }
    return PullRequest(**fields)


def _poller(
    tmp_path: Path, store: UnitStore, locks: Path, pages: list[list[PullRequest]]
) -> Poller:
    calls = iter(pages)
    return Poller(
        repo="example/app",
        state_path=tmp_path / "prs-app.json",
        list_prs=lambda: next(calls),
        dispatch=partial(
            events.build_dispatch(
                store, restack=Recorder(), claim=events.build_claim(locks), log=lambda m: None
            ),
            repo="app",
        ),
    )


def test_a_hold_that_arrives_mid_build_survives_the_build_finishing(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    """The build ends by recording `in_review`. A hold written before that is
    overwritten by it; a hold reported again after it stands."""
    held = _pull(labels=("agent-hold",))
    poller = _poller(tmp_path, store, locks, [[_pull()], [held], [held]])
    poller.poll()
    store.set_state("add-marker/1", RUNNING)

    with branch_lock("spec/add-marker/1", root=locks):
        poller.poll()
        store.set_state("add-marker/1", IN_REVIEW)  # how the build ends

    poller.poll()

    assert store.get("add-marker/1").state == events.HELD


def test_a_review_that_arrives_mid_rework_is_not_dropped(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    """The build clears the feedback it started with once it has pushed. A
    new review written mid-build was cleared with it; reported again after the
    build, it requeues the unit with the reviewer's words."""
    reviewed = _pull(conversation=("c9",), comment_bodies=("rename the flag too",))
    poller = _poller(tmp_path, store, locks, [[_pull()], [reviewed], [reviewed]])
    poller.poll()
    store.set_state("add-marker/1", RUNNING)
    store.set_feedback("add-marker/1", "an earlier review")

    with branch_lock("spec/add-marker/1", root=locks):
        poller.poll()
        store.set_feedback("add-marker/1", "")  # how the build ends
        store.set_state("add-marker/1", IN_REVIEW)

    poller.poll()

    assert store.get("add-marker/1").state == PLANNED
    assert store.get("add-marker/1").feedback == "rename the flag too"


# A pull request number names a unit only within its repo --------------------


@pytest.fixture
def shared_number(tmp_path: Path) -> UnitStore:
    """Two repos that have both reached pull request 5. The other repo's unit
    is older, finished, and first in the store — the one a lookup by number
    alone returns."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("feature/1", repo="platform"), unit("add-marker/1")])
    store.set_state("feature/1", MERGED, pr=5, branch="spec/feature/1")
    store.set_state("add-marker/1", IN_REVIEW, pr=5, branch="spec/add-marker/1")
    return store


def test_a_merge_reaches_the_unit_in_the_repo_it_was_reported_for(
    shared_number: UnitStore,
) -> None:
    """Matched on the number alone, this merge was recorded against the other
    repo's unit, and the one that merged stayed in review."""
    before = shared_number.history("feature/1")
    removed: list[tuple[str, str]] = []

    events.on_merged(
        5,
        repo="app",
        store=shared_number,
        restack=Recorder(),
        remove_worktree=lambda repo, branch: removed.append((repo, branch)),
        log=lambda m: None,
    )

    assert shared_number.get("add-marker/1").state == MERGED
    assert shared_number.history("feature/1") == before
    assert removed == [("app", "spec/add-marker/1")]


@pytest.mark.parametrize(
    "event",
    [
        lambda store: events.on_rework(
            5, repo="app", reason="new comment", store=store, log=lambda m: None
        ),
        lambda store: events.on_hold(5, repo="app", store=store, log=lambda m: None),
        lambda store: events.on_closed(5, repo="app", store=store, log=lambda m: None),
    ],
    ids=["rework", "hold", "closed"],
)
def test_an_event_leaves_the_other_repos_unit_alone(shared_number: UnitStore, event) -> None:
    """A comment on one repo's pull request requeued the other repo's finished
    unit, which was then built again for feedback that was not its own."""
    before = shared_number.history("feature/1")

    event(shared_number)

    assert shared_number.get("feature/1").state == MERGED
    assert shared_number.history("feature/1") == before
    assert shared_number.get("add-marker/1").state != IN_REVIEW


def test_a_number_only_another_repo_has_matches_nothing(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("feature/1", repo="platform")])
    store.set_state("feature/1", IN_REVIEW, pr=5, branch="spec/feature/1")
    logged: list[str] = []
    recorder = Recorder()

    for event in ("merged", "closed", "hold", "rework"):
        events.build_dispatch(store, restack=recorder, log=logged.append)(event, 5, repo="app")

    assert store.get("feature/1").state == IN_REVIEW
    assert recorder.restacked == []
    assert len(logged) == 4
    assert all("#5" in line and "app" in line for line in logged)


def test_the_review_is_fetched_from_the_repo_the_event_was_reported_for(
    shared_number: UnitStore,
) -> None:
    """The fetchers are bound through the same lookup, so they asked the other
    repo for a review of a pull request that was never its own."""
    asked: list[tuple[str, int]] = []

    def fetch(repo: str, number: int) -> list[str]:
        asked.append((repo, number))
        return []

    events.build_dispatch(
        shared_number, restack=Recorder(), fetch_review=fetch, log=lambda m: None
    )("rework", 5, repo="app", reason="new comment")

    assert asked == [("app", 5)]
