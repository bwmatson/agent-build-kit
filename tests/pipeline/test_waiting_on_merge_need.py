"""A merge edge holds a start until the parent merged and the tick has the merge
(spec: needs-can-wait-for-a-merge). The kit's checkout is a throwaway git repository and the
tick record is made by hand."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.loaded_code import LoadedCode
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    SATISFIED,
    UnitState,
    waiting_on,
)
from tests.factories import commit, git, init_repo, stored_unit

UNKNOWN = "0" * 40


class Kit:
    """A checkout whose head holds `merged` and not `unmerged`, which sits on another branch."""

    def __init__(self, path: Path) -> None:
        init_repo(path)
        self.path = path
        commit(path, "first")
        self.merged = commit(path, "second")
        self.head = git(path, "rev-parse", "HEAD")
        git(path, "checkout", "-q", "-b", "elsewhere")
        self.unmerged = commit(path, "third")
        git(path, "checkout", "-q", "main")

    def loaded(self, *, number: int = 5, head: str | None = None) -> LoadedCode:
        return LoadedCode(
            number=number, kit_repo="app", kit_root=str(self.path), kit_head=head or self.head
        )


@pytest.fixture
def kit(tmp_path: Path) -> Kit:
    return Kit(tmp_path / "kit")


def held_by(parent_state: UnitState, loaded: LoadedCode, *, repo: str = "app", **parent):
    """The units a planned `feature/1` with a merge `Needs:` on `base/1` waits for."""
    base = stored_unit("base/1", change="base", repo=repo, state=parent_state, **parent)
    child = stored_unit(
        "feature/1",
        change="feature",
        depends_on=("base/1",),
        needs=("base/1",),
        merge_needs=("base/1",),
    )
    return [u.id for u in waiting_on(child, [base, child], loaded)]


def test_a_parent_in_review_leaves_a_merge_dependent_waiting(kit: Kit) -> None:
    assert held_by(IN_REVIEW, kit.loaded()) == ["base/1"]


def test_a_merged_kit_parent_whose_commit_is_in_the_head_releases_the_dependent(kit: Kit) -> None:
    loaded = kit.loaded()

    assert held_by(MERGED, loaded, merge_sha=kit.unmerged, merged_tick=1) == ["base/1"]
    assert held_by(MERGED, loaded, merge_sha=kit.merged, merged_tick=5) == []


@pytest.mark.parametrize("sha", ["unmerged", "unknown"])
def test_a_merge_commit_the_head_lacks_or_the_checkout_does_not_know_holds_it(
    kit: Kit, sha: str
) -> None:
    merge_sha = kit.unmerged if sha == "unmerged" else UNKNOWN

    assert held_by(MERGED, kit.loaded(number=9), merge_sha=merge_sha, merged_tick=1) == ["base/1"]


def test_a_merged_parent_with_no_record_of_its_merge_counts_as_loaded(kit: Kit) -> None:
    """Everything merged before the fields existed: no history is rewritten, nothing delayed."""
    loaded = kit.loaded(number=5)

    assert held_by(MERGED, loaded, merged_tick=5) == ["base/1"]
    assert held_by(MERGED, loaded) == []


def test_the_tick_rule_releases_only_for_a_later_tick_than_the_one_that_saw_the_merge(
    kit: Kit,
) -> None:
    """Without a merge commit to ask the head about, the tick number decides."""
    assert held_by(MERGED, kit.loaded(number=5), merged_tick=5) == ["base/1"]
    assert held_by(MERGED, kit.loaded(number=6), merged_tick=5) == []


def test_an_unknown_head_falls_back_to_the_tick_rule(kit: Kit) -> None:
    unreadable = LoadedCode(number=5, kit_repo="app", kit_root=str(kit.path), kit_head=None)

    assert held_by(MERGED, unreadable, merge_sha=kit.merged, merged_tick=5) == ["base/1"]
    assert (
        held_by(
            MERGED, unreadable.model_copy(update={"number": 6}), merge_sha=kit.merged, merged_tick=5
        )
        == []
    )


def test_a_parent_in_another_repository_needs_the_merge_and_a_later_tick(kit: Kit) -> None:
    """The sha test is for the kit's repository alone; for any other the tick rule decides,
    so a merge the running tick saw is acted on by the next one."""
    same = kit.loaded(number=5)
    later = kit.loaded(number=6)

    assert held_by(IN_REVIEW, later, repo="platform") == ["base/1"]
    assert held_by(MERGED, same, repo="platform", merge_sha=kit.merged, merged_tick=5) == ["base/1"]
    assert held_by(MERGED, later, repo="platform", merge_sha=kit.merged, merged_tick=5) == []


def test_a_satisfied_parent_is_met_once_its_work_landed(kit: Kit) -> None:
    """A satisfied unit never merges itself; it is met when the same-repo unit it was built
    on has merged, and that merge is in the code like any other."""
    pred = stored_unit("pred/1", change="pred", state=IN_REVIEW)
    base = stored_unit("base/1", change="base", state=SATISFIED, depends_on=("pred/1",))
    child = stored_unit(
        "feature/1", change="feature", depends_on=("base/1",), merge_needs=("base/1",)
    )
    loaded = kit.loaded(number=9)

    assert [u.id for u in waiting_on(child, [pred, base, child], loaded)] == ["base/1"]
    merged = pred.model_copy(update={"state": MERGED, "merge_sha": kit.merged, "merged_tick": 1})
    assert waiting_on(child, [merged, base, child], loaded) == []


def test_a_planned_unit_on_a_review_edge_is_released_in_review(kit: Kit) -> None:
    base = stored_unit("base/1", change="base", state=IN_REVIEW)
    plain = stored_unit("plain/1", change="plain", depends_on=("base/1",), needs=("base/1",))
    merge = stored_unit(
        "merge/1",
        change="merge",
        depends_on=("base/1",),
        needs=("base/1",),
        merge_needs=("base/1",),
    )
    graph = [base, plain, merge]

    assert waiting_on(plain, graph, kit.loaded()) == []
    assert [u.id for u in waiting_on(merge, graph, kit.loaded())] == ["base/1"]


def test_an_implied_target_still_holds(kit: Kit) -> None:
    """A `Needs:` the chain implies is recorded in `needs` but not in `depends_on`; for a
    merge need the wait must hold all the same."""
    base = stored_unit("base/1", change="base", state=IN_REVIEW)
    child = stored_unit("feature/1", change="feature", needs=("base/1",), merge_needs=("base/1",))

    assert [u.id for u in waiting_on(child, [base, child], kit.loaded())] == ["base/1"]


@pytest.mark.parametrize("dropped", [UnitState.UNPLANNED, UnitState.RETIRED])
def test_a_dropped_parent_never_waits(kit: Kit, dropped: UnitState) -> None:
    assert held_by(IN_REVIEW, kit.loaded()) == ["base/1"]
    assert held_by(dropped, kit.loaded()) == []
