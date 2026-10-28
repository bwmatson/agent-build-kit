"""A merged pull request settles before its unit is merged (spec: merged-waits-for-ci).

The merge event records the merge and moves the unit to `settling`; `settled` makes it `merged`
once every check has completed. A settling unit counts as in progress, holds a dependent that
waits for its merge and not one that waits only for its review, and cannot be requeued.
"""

from pathlib import Path

import pytest

from agent_build_kit.cli.pipeline import requeue_refusal
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    SETTLING,
    in_progress,
    ready_units,
)
from tests.factories import stored_unit as unit

SHA = "abc123"
TICK = 9


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=4, branch="spec/add-marker/1")
    return store


def merge(store: UnitStore) -> None:
    events.on_merged(
        4,
        repo="app",
        store=store,
        restack=lambda **k: None,
        merge_record=lambda unit: (SHA, TICK),
        log=lambda m: None,
    )


def settled(store: UnitStore) -> bool:
    dispatch = events.build_dispatch(
        store,
        restack=lambda **k: None,
        merge_record=lambda unit: (SHA, TICK),
        log=lambda m: None,
    )
    return dispatch("settled", 4, repo="app")


def test_a_merged_pull_request_moves_its_unit_to_settling_with_the_merge_recorded(
    store: UnitStore,
) -> None:
    merge(store)

    settling = store.get("add-marker/1")
    assert settling.state == SETTLING
    assert settling.merge_sha == SHA
    assert settling.merged_tick is None
    assert settling.pr == 4
    first = settling.pulls[0]
    assert (first.number, first.role, first.merge_sha) == (4, "original", SHA)
    assert first.merged_at is not None
    assert in_progress(settling)


def test_a_settling_parent_holds_a_merge_dependent_and_not_a_review_dependent() -> None:
    parent = unit("base/1", change="base", state=SETTLING, pr=1, branch="spec/base/1")
    by_review = unit("reviewed/1", change="reviewed", depends_on=(parent.id,))
    by_merge = unit(
        "merged/1",
        change="merged",
        depends_on=(parent.id,),
        needs=(parent.id,),
        merge_needs=(parent.id,),
    )

    ready = ready_units(
        [parent, by_review, by_merge], max_concurrent=10, depth_cap=10, max_units_in_progress=10
    )

    assert [u.id for u in ready] == ["reviewed/1"]


def test_settled_makes_the_unit_merged_and_sets_its_merged_tick(store: UnitStore) -> None:
    merge(store)

    assert settled(store) is True

    done = store.get("add-marker/1")
    assert done.state == MERGED
    assert done.merged_tick == TICK
    assert done.merge_sha == SHA


@pytest.mark.parametrize("state", [SETTLING, MERGED])
def test_a_requeue_of_a_settling_or_merged_unit_names_settle_and_the_late_fix(state) -> None:
    refusal = requeue_refusal(unit("add-marker/1", state=state, pr=4))

    assert refusal is not None
    assert "abk settle" in refusal
    assert "late fix" in refusal.replace("-", " ")
