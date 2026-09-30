"""What the pipeline does when GitHub tells it something changed.

`gh_poller` notices; this decides. Until these handlers existed nothing moved
past `open`: a merged PR left its unit sitting there and its children stacked
on a branch that no longer needed to exist.

The one that carries real weight is **merged**. Merging the bottom of a stack
changes what every branch above it should sit on, and getting that wrong is
how a child PR starts showing its parent's diff as its own — or worse, how a
force-push lands commits nobody reviewed on a base that already has them.
"""

from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest, ReviewNote
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.restack import Moved, RestackConflict
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import CLOSED, IN_REVIEW, MERGED, PLANNED, RUNNING
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
    events.on_merged(1, store=store, restack=Recorder())

    assert store.get("add-marker/1").state == MERGED


def test_merging_the_bottom_restacks_what_was_on_top(store: UnitStore) -> None:
    """The child's branch still sits on its parent's, which main now contains.
    Left alone, its PR shows both units' work as its own diff."""
    recorder = Recorder()

    events.on_merged(1, store=store, restack=recorder)

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

    events.on_merged(1, store=store, restack=recorder)

    moved = {r["branch"]: r["new_base"] for r in recorder.restacked}
    assert moved["spec/c/2"] == "main"
    assert moved["spec/c/3"] == "spec/c/2", "still stacked on the open middle"


def test_a_merge_we_have_no_unit_for_is_ignored(store: UnitStore) -> None:
    """Someone else's PR on a spec/ branch, or a unit removed from the store.
    Restacking against a unit we don't know is how the wrong branch moves."""
    recorder = Recorder()

    events.on_merged(999, store=store, restack=recorder)

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

    events.on_merged(1, store=store, restack=restack)

    assert moved == ["spec/c/3"]
    assert store.get("c/1").state == MERGED, "the merge itself still stands"


def test_a_closed_pr_marks_its_unit_closed(store: UnitStore) -> None:
    events.on_closed(1, store=store)

    assert store.get("add-marker/1").state == CLOSED


def test_closing_a_parent_leaves_its_children_alone(store: UnitStore) -> None:
    """Closing is a human decision about one unit. Cascading it would discard
    work on branches nobody asked to drop."""
    events.on_closed(1, store=store)

    assert store.get("add-marker/2").state == IN_REVIEW


def test_rework_is_recorded_against_the_unit(store: UnitStore) -> None:
    """The reason has to survive the poll: the next tick is a new process, and
    rebuilding without knowing what the reviewer said would reproduce the same
    code at full price."""
    events.on_rework(1, reason="new comment", store=store)

    assert "new comment" in str(store.get("add-marker/1").history[-1])


def test_a_held_unit_is_recorded_so_nothing_reworks_it(store: UnitStore) -> None:
    events.on_hold(1, store=store)

    assert store.get("add-marker/1").state == events.HELD


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


def test_the_poller_s_events_reach_the_handlers(tmp_path: Path) -> None:
    """The names in the dispatch table are the poller's contract; a typo here
    is an event that silently does nothing."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1")])
    store.set_state("c/1", IN_REVIEW, pr=1, branch="spec/c/1")
    dispatch = events.build_dispatch(store, restack=Recorder(), log=lambda m: None)

    dispatch("merged", 1)

    assert store.get("c/1").state == MERGED


def test_an_unknown_event_is_logged_rather_than_ignored(tmp_path: Path) -> None:
    """If the poller grows an event this doesn't handle, the silence would
    look exactly like a working pipeline with nothing to do."""
    store = UnitStore(tmp_path / "units.json")
    logged: list[str] = []
    dispatch = events.build_dispatch(store, restack=Recorder(), log=logged.append)

    dispatch("something-new", 1)

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
    events.on_rework(1, reason="new comment", pull=rework_pull("Use a Sequence here"), store=store)

    assert store.get("add-marker/1").feedback == "Use a Sequence here"


def test_a_reworked_unit_goes_back_in_the_queue(store: UnitStore) -> None:
    """Recording it and leaving the unit open would mean the feedback sat
    there until someone noticed by hand."""
    events.on_rework(1, reason="new comment", pull=rework_pull("Use a Sequence"), store=store)

    assert store.get("add-marker/1").state == PLANNED


def test_feedback_with_no_comment_still_says_why(store: UnitStore) -> None:
    """A failing check dispatches rework too, and its reason is all there is."""
    events.on_rework(1, reason="failing checks: tier1", pull=bare_pull(), store=store)

    assert "failing checks: tier1" in store.get("add-marker/1").feedback


def test_a_held_unit_is_not_requeued_by_a_comment(store: UnitStore) -> None:
    """Hold means a human has taken it over. Requeuing would have the agent
    push over the work they are in the middle of."""
    events.on_hold(1, store=store)

    events.on_rework(1, reason="new comment", pull=rework_pull("thoughts?"), store=store)

    assert store.get("add-marker/1").state == events.HELD
    assert store.get("add-marker/1").feedback == ""


def test_a_merged_unit_s_worktree_is_removed(store: UnitStore) -> None:
    """Nothing else ever removes one. Left alone they accumulate a full
    checkout per unit — app already carries nine from earlier runs — and
    every one of them is a working tree git has to keep track of."""
    removed: list[str] = []

    events.on_merged(
        1,
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

    events.on_merged(1, store=store, restack=Recorder(), remove_worktree=refuse)

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
    events.on_closed(1, store=store)

    assert store.get("add-marker/1").state == CLOSED


def test_rework_carries_the_reviewer_s_inline_words(store: UnitStore) -> None:
    """A review's bodies can be empty with the whole content one inline
    comment on a line — which `gh pr list` does not return at
    all. Feedback saying only "changes requested" is the uselessness the rework
    path exists to avoid, so the words are fetched when they are needed."""
    events.on_rework(
        1,
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

    events.on_rework(1, store=store, reason="new comment", log=lambda m: None)

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

    events.on_rework(1, store=store, reason="new comment", pull=pull, log=lambda m: None)

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


def test_the_failed_run_is_found_from_the_check_s_link() -> None:
    from agent_build_kit.pipeline.events import LOG_PREFIX, RUN_URL

    url = "https://github.com/o/r/actions/runs/36247510537/job/108419332762"
    match = RUN_URL.search(url)
    assert match is not None and match["run"] == "36247510537"
    line = "config-check\tRun pytest\t2026-01-01T14:09:07.0730165Z 1 failed, 14 passed"
    assert LOG_PREFIX.sub("", line) == "1 failed, 14 passed"


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
            1, store=store, restack=recorder, claim=events.build_claim(locks), log=lambda m: None
        )

    assert handled is False, "deferred, so the poller reports it again"
    assert store.get("add-marker/1").state == RUNNING
    assert recorder.restacked == []


@pytest.mark.parametrize(
    "handle",
    [
        lambda store, claim: events.on_rework(
            1, reason="new comment", store=store, claim=claim, log=lambda m: None
        ),
        lambda store, claim: events.on_hold(1, store=store, claim=claim, log=lambda m: None),
        lambda store, claim: events.on_closed(1, store=store, claim=claim, log=lambda m: None),
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
        dispatch=events.build_dispatch(
            store, restack=Recorder(), claim=events.build_claim(locks), log=lambda m: None
        ),
    )


def test_a_hold_that_arrives_mid_build_survives_the_build_finishing(
    tmp_path: Path, store: UnitStore, locks: Path
) -> None:
    """The build ends by recording `in_review`. A hold written before that is
    overwritten by it; a hold reported again after it stands."""
    held = _pull(labels=("agent:hold",))
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
