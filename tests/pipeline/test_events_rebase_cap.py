"""A merge cascades a restack only as deep as the rebase cap allows.

A dependent beyond it is held, not restacked, and its parent's branch is kept;
a later merge in the same repo reconsiders it.
"""

from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, SATISFIED
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.factories import stored_unit as unit


class Recorder:
    def __init__(self) -> None:
        self.restacked: list[dict] = []

    def __call__(self, **kwargs) -> None:
        self.restacked.append(kwargs)

    @property
    def branches(self) -> list[str]:
        return [r["branch"] for r in self.restacked]


def deep_store(tmp_path: Path) -> UnitStore:
    """c/2 on c/1, c/3 on c/2, and c/4 on both c/1 and c/3.

    Merging c/1 leaves c/2 at depth 1 and c/4 at depth 3: c/4 is a direct
    dependent of c/1 that sits deeper than c/2. c/9 is an unrelated unit in the
    same repo.
    """
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("c/1"),
            unit("c/2", depends_on=("c/1",)),
            unit("c/3", depends_on=("c/2",)),
            unit("c/4", depends_on=("c/1", "c/3")),
            unit("c/9"),
        ]
    )
    for n in (1, 2, 3, 4, 9):
        store.set_state(f"c/{n}", IN_REVIEW, pr=n, branch=f"spec/c/{n}")
    return store


def merge(store: UnitStore, pr: int, *, cap: int, recorder: Recorder, deleted: list[str]) -> None:
    events.on_merged(
        pr,
        repo="app",
        store=store,
        restack=recorder,
        delete_branch=lambda repo, branch: deleted.append(branch),
        rebase_cap=cap,
    )


def test_a_dependent_within_the_rebase_cap_is_restacked_as_before(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    recorder, deleted = Recorder(), []

    merge(store, 1, cap=3, recorder=recorder, deleted=deleted)

    assert sorted(recorder.branches) == ["spec/c/2", "spec/c/4"]
    assert store.get("c/4").state == IN_REVIEW
    assert deleted == ["spec/c/1"]


def test_a_dependent_beyond_the_rebase_cap_is_held_not_restacked(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    recorder, deleted = Recorder(), []

    merge(store, 1, cap=2, recorder=recorder, deleted=deleted)

    assert recorder.branches == ["spec/c/2"], "c/2 is at depth 1, c/4 at depth 3"
    assert store.get("c/2").state == IN_REVIEW
    assert store.get("c/4").state == HELD


def test_the_hold_names_the_depth_and_the_cap(tmp_path: Path) -> None:
    store = deep_store(tmp_path)

    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])

    last = store.get("c/4").history[-1]
    assert last["state"] == HELD
    assert store.get("c/4").held_by == "depth"
    assert "depth 3" in last["note"] and "cap 2" in last["note"]


def test_the_hold_records_its_cause_and_the_base_it_is_still_on_as_fields(
    tmp_path: Path,
) -> None:
    store = deep_store(tmp_path)

    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])

    held = store.get("c/4")
    assert held.history[-1].get("cause") == Cause.DEPTH
    assert held.held_base == "spec/c/1"


def test_the_branch_of_a_dependent_held_for_depth_is_not_deleted(tmp_path: Path) -> None:
    """c/4's branch still carries c/1's commits; deleting c/1's branch strands it."""
    store = deep_store(tmp_path)
    deleted: list[str] = []

    merge(store, 1, cap=2, recorder=Recorder(), deleted=deleted)

    assert deleted == []


def test_a_later_merge_restacks_a_unit_whose_depth_has_fallen(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    assert store.get("c/4").state == HELD
    recorder = Recorder()

    # c/2 merges: c/4 is not its dependent, so only reconsideration reaches it.
    merge(store, 2, cap=2, recorder=recorder, deleted=[])

    assert "spec/c/4" in recorder.branches
    assert store.get("c/4").state == IN_REVIEW


def test_a_merge_of_an_unrelated_unit_reconsiders_a_held_one(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    store.set_state("c/2", MERGED)  # its depth fell with no event of its own
    recorder = Recorder()

    merge(store, 9, cap=2, recorder=recorder, deleted=[])

    assert recorder.branches == ["spec/c/4"]
    assert recorder.restacked[0]["new_base"] == "spec/c/3"
    assert store.get("c/4").state == IN_REVIEW


def test_a_unit_still_beyond_the_cap_stays_held(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    merge(store, 1, cap=1, recorder=Recorder(), deleted=[])
    assert store.get("c/4").state == HELD
    recorder = Recorder()

    deleted: list[str] = []

    merge(store, 2, cap=1, recorder=recorder, deleted=deleted)

    assert "spec/c/4" not in recorder.branches
    assert store.get("c/4").state == HELD
    assert deleted == ["spec/c/2"]


def test_a_merge_in_another_repo_does_not_reconsider_it(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    store.upsert([unit("p/1", repo="platform")])
    store.set_state("p/1", IN_REVIEW, pr=50, branch="spec/p/1")
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    store.set_state("c/2", MERGED)
    recorder = Recorder()

    merge(store, 50, cap=2, recorder=recorder, deleted=[])

    assert recorder.restacked == []
    assert store.get("c/4").state == HELD


def busy_on(unit_id: str):
    def claim(u):
        if u.id == unit_id:
            raise BranchBusy("building")
        return nullcontext()

    return claim


def test_an_unrelated_merge_deletes_its_own_branch_while_another_unit_is_held(
    tmp_path: Path,
) -> None:
    store = deep_store(tmp_path)
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    deleted: list[str] = []

    merge(store, 9, cap=2, recorder=Recorder(), deleted=deleted)

    assert deleted == ["spec/c/9"]
    assert store.get("c/4").state == HELD


def test_a_child_being_built_is_retargeted_not_held_for_depth(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    retargeted: list[tuple[str, str]] = []
    deleted: list[str] = []

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Recorder(),
        delete_branch=lambda repo, branch: deleted.append(branch),
        claim=busy_on("c/4"),
        retarget=lambda u, base: retargeted.append((u.id, base)),
        rebase_cap=2,
    )

    assert store.get("c/4").state == IN_REVIEW
    assert ("c/4", "spec/c/3") in retargeted
    assert deleted == []


def test_a_child_held_for_depth_has_its_pr_retargeted(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    retargeted: list[tuple[str, str]] = []

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Recorder(),
        retarget=lambda u, base: retargeted.append((u.id, base)),
        rebase_cap=2,
    )

    assert store.get("c/4").state == HELD
    assert retargeted == [("c/4", "spec/c/3")]


def test_a_failing_retarget_still_leaves_the_unit_held_with_its_branch_kept(
    tmp_path: Path,
) -> None:
    store = deep_store(tmp_path)
    deleted: list[str] = []
    logged: list[str] = []

    def retarget(u, base) -> None:
        raise RuntimeError("forge down")

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Recorder(),
        delete_branch=lambda repo, branch: deleted.append(branch),
        retarget=retarget,
        rebase_cap=2,
        log=logged.append,
    )

    assert store.get("c/4").state == HELD
    assert deleted == []
    assert any("not retargeted" in line for line in logged)


def test_a_hold_from_a_reviewer_is_left_alone(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    events.on_hold(4, repo="app", store=store)
    store.set_state("c/2", MERGED)
    recorder = Recorder()

    merge(store, 9, cap=5, recorder=recorder, deleted=[])

    assert recorder.restacked == []
    assert store.get("c/4").state == HELD


def test_a_hold_that_needs_a_human_is_left_alone(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    store.set_state("c/4", HELD, note="needs a human: the profile is not implemented")
    recorder = Recorder()

    merge(store, 9, cap=5, recorder=recorder, deleted=[])

    assert recorder.restacked == []
    assert store.get("c/4").state == HELD


def test_a_depth_hold_a_reviewer_then_also_holds_is_the_labels_and_a_merge_leaves_it(
    tmp_path: Path,
) -> None:
    """The label takes the hold over, so a later merge that would free the unit
    for depth leaves it held while the label is on its pull request."""
    store = deep_store(tmp_path)
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    events.on_hold(4, repo="app", store=store)
    assert store.get("c/4").held_by == "reviewer"
    store.set_state("c/2", MERGED)
    recorder = Recorder()

    merge(store, 9, cap=2, recorder=recorder, deleted=[])

    assert recorder.restacked == []
    assert store.get("c/4").state == HELD
    assert store.get("c/4").held_by == "reviewer"


def test_releasing_a_depth_hold_the_label_took_over_restores_the_depth_hold(
    tmp_path: Path,
) -> None:
    store = deep_store(tmp_path)
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    held_note = store.get("c/4").note
    events.on_hold(4, repo="app", store=store)

    events.on_release(4, repo="app", store=store, restack=Recorder(), rebase_cap=2)

    stored = store.get("c/4")
    assert (stored.state, stored.held_by) == (HELD, "depth")
    assert stored.note == held_note
    assert events.held_for_depth(stored)


def test_a_depth_hold_the_label_took_over_is_restacked_by_a_merge_after_its_release(
    tmp_path: Path,
) -> None:
    store = deep_store(tmp_path)
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    events.on_hold(4, repo="app", store=store)
    events.on_release(4, repo="app", store=store)
    store.set_state("c/2", MERGED)
    recorder = Recorder()

    merge(store, 2, cap=2, recorder=recorder, deleted=[])

    moved = [
        {key: call[key] for key in ("branch", "old_base", "new_base")}
        for call in recorder.restacked
    ]
    assert {"branch": "spec/c/4", "old_base": "spec/c/1", "new_base": "spec/c/3"} in moved
    assert store.get("c/4").state == IN_REVIEW


def test_a_release_after_a_merge_brought_the_unit_within_the_cap_restacks_it(
    tmp_path: Path,
) -> None:
    store = deep_store(tmp_path)
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    events.on_hold(4, repo="app", store=store)
    store.set_state("c/2", MERGED)
    recorder = Recorder()
    merge(store, 9, cap=2, recorder=recorder, deleted=[])
    assert recorder.restacked == [], "the label's hold is not freed by the merge"

    events.on_release(4, repo="app", store=store, restack=recorder, rebase_cap=2)

    assert recorder.branches == ["spec/c/4"]
    assert recorder.restacked[0]["old_base"] == "spec/c/1"
    assert recorder.restacked[0]["new_base"] == "spec/c/3"
    assert store.get("c/4").state == IN_REVIEW


def test_a_restack_that_raises_leaves_the_unit_in_review_and_the_others_reconsidered(
    tmp_path: Path,
) -> None:
    store = deep_store(tmp_path)
    store.upsert([unit("c/5", depends_on=("c/1", "c/3"))])
    store.set_state("c/5", IN_REVIEW, pr=5, branch="spec/c/5")
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    assert store.get("c/4").state == store.get("c/5").state == HELD
    store.set_state("c/2", MERGED)
    seen: list[str] = []
    logged: list[str] = []

    def restack(**kwargs) -> None:
        seen.append(kwargs["branch"])
        if kwargs["branch"] == "spec/c/4":
            raise RuntimeError("checks fail")

    events.on_merged(9, repo="app", store=store, restack=restack, rebase_cap=2, log=logged.append)

    assert seen == ["spec/c/4", "spec/c/5"]
    assert store.get("c/4").state == IN_REVIEW
    assert any("c/4: restack onto" in line and "failed" in line for line in logged)


def test_a_busy_held_unit_stays_held_with_its_record_unchanged(tmp_path: Path) -> None:
    store = deep_store(tmp_path)
    merge(store, 1, cap=2, recorder=Recorder(), deleted=[])
    store.set_state("c/2", MERGED)
    before = len(store.get("c/4").history)
    recorder = Recorder()

    events.on_merged(
        9, repo="app", store=store, restack=recorder, claim=busy_on("c/4"), rebase_cap=2
    )

    assert recorder.restacked == []
    assert store.get("c/4").state == HELD
    assert len(store.get("c/4").history) == before

    # Found again by the next merge, once the build is done.
    events.on_merged(9, repo="app", store=store, restack=recorder, rebase_cap=2)
    assert recorder.branches == ["spec/c/4"]


@pytest.mark.parametrize("cap", [3, 4])
def test_a_cap_at_or_above_the_depth_holds_nothing(tmp_path: Path, cap: int) -> None:
    store = deep_store(tmp_path)

    merge(store, 1, cap=cap, recorder=Recorder(), deleted=[])

    assert all(u.state != HELD for u in store.all())


def test_a_dependent_through_a_satisfied_unit_is_held_for_depth_like_a_direct_one(
    tmp_path: Path,
) -> None:
    """c/7 names the satisfied c/2 (which sat on c/1), so merging c/1 reaches it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("c/1"),
            unit("c/2", depends_on=("c/1",)),
            unit("c/5"),
            unit("c/6", depends_on=("c/5",)),
            unit("c/7", depends_on=("c/2", "c/6")),
        ]
    )
    for n in (1, 5, 6, 7):
        store.set_state(f"c/{n}", IN_REVIEW, pr=n, branch=f"spec/c/{n}")
    store.set_state("c/2", SATISFIED)
    recorder, deleted = Recorder(), []

    merge(store, 1, cap=2, recorder=recorder, deleted=deleted)

    assert recorder.branches == []
    assert store.get("c/7").state == HELD
    assert deleted == []
