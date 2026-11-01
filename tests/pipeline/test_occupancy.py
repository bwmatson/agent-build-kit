"""Occupancy is a pure function of plain data: live locks, unexpired `starting` markers, runs the
caller knows of and recorded usage pauses, counted per project, per account and in the emergency
lane, then held to the limits. A lease is recorded and takes neither a place nor a worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_build_kit.pipeline.occupancy import Limits, emergency_free, free, occupied
from agent_build_kit.pipeline.unit_store import Starting
from agent_build_kit.pipeline.units import RUNNING, ProjectKey, Unit
from tests.factories import new_unit

NOW = datetime(2030, 1, 1, 12, tzinfo=UTC)


def key(repo: str = "app") -> ProjectKey:
    return ProjectKey(repo=repo)


def on_branch(uid: str, **fields):
    """A unit with its branch recorded, so a lock on `spec/<id>` names it."""
    return new_unit(uid, branch=f"spec/{uid}", **fields)


def locks(*ids: str) -> set[str]:
    return {f"spec/{uid}" for uid in ids}


def marked(uid: str, *, lapses: timedelta, repo: str = "app"):
    return new_unit(uid, repo=repo).model_copy(
        update={"starting": Starting(worker="w1", until=NOW + lapses)}
    )


def paused_unit(uid: str, **fields):
    return on_branch(uid, **fields).model_copy(
        update={"state": RUNNING, "paused_until": NOW + timedelta(hours=1)}
    )


def test_a_live_lock_an_unexpired_marker_and_a_known_run_each_occupy_a_slot():
    units = [
        on_branch("a/1"),
        marked("c/1", lapses=timedelta(minutes=5)),
        new_unit("d/1"),
        new_unit("e/1"),
    ]

    found = occupied(units, locks=locks("a/1"), leases=(), held={"e/1"}, now=NOW)

    assert found.projects == {key(): 3}
    assert found.workers == {key(): 3}


def test_a_lease_alone_takes_neither_a_place_nor_a_worker_and_is_recorded():
    found = occupied([new_unit("a/1")], locks=(), leases={"a/1"}, now=NOW)

    assert found.projects == {}
    assert found.workers == {}
    assert found.leased == {key(): 1}
    assert free(found, Limits(stacks=1, in_progress=1), key()) == 1


def test_a_recorded_usage_pause_occupies_a_slot_with_no_lock():
    idle = new_unit("b/1").model_copy(update={"state": RUNNING})

    found = occupied([paused_unit("a/1"), idle], locks=(), leases=(), now=NOW)

    assert found.projects == {key(): 1}


def test_an_expired_marker_occupies_nothing():
    found = occupied([marked("a/1", lapses=timedelta(seconds=-1))], locks=(), leases=(), now=NOW)

    assert found.projects.get(key(), 0) == 0


def test_a_unit_named_by_a_lock_a_marker_and_a_known_run_is_counted_once():
    unit = marked("a/1", lapses=timedelta(minutes=5)).model_copy(update={"branch": "spec/a/1"})

    found = occupied([unit], locks=locks("a/1"), leases={"a/1"}, held={"a/1"}, now=NOW)

    assert found.projects == {key(): 1}
    assert found.workers == {key(): 1}


def test_projects_are_counted_apart():
    units = [on_branch("a/1", repo="app"), on_branch("b/1", repo="platform")]

    found = occupied(units, locks=locks("a/1", "b/1"), leases=(), now=NOW)

    assert found.projects == {key("app"): 1, key("platform"): 1}


def test_units_are_counted_under_their_accounts():
    units = [
        on_branch("a/1", repo="app"),
        on_branch("b/1", repo="platform"),
        on_branch("c/1"),
    ]

    def account_of(unit: Unit) -> str | None:
        return "kit" if unit.repo == "platform" else None

    found = occupied(
        units, locks=locks("a/1", "b/1", "c/1"), leases=(), now=NOW, account_of=account_of
    )

    assert found.accounts == {None: 2, "kit": 1}


def test_the_emergency_lane_counts_the_occupying_units_it_holds():
    units = [on_branch("a/1"), on_branch("b/1"), on_branch("c/1")]

    found = occupied(units, locks=locks("a/1", "b/1"), leases=(), now=NOW, lane={"b/1", "c/1"})

    assert found.emergency == {key(): 1}


def test_free_slots_are_the_workers_left_in_the_project():
    units = [on_branch("a/1"), on_branch("b/1", repo="platform")]
    found = occupied(units, locks=locks("a/1", "b/1"), leases=(), now=NOW)

    limits = Limits(stacks=3)

    assert free(found, limits, key("app")) == 2
    assert free(found, limits, key("web")) == 3


def test_a_full_project_has_no_free_slot():
    found = occupied([on_branch("a/1")], locks=locks("a/1"), leases=(), now=NOW)

    assert free(found, Limits(stacks=1), key()) == 0


def test_a_lane_unit_holds_a_worker_for_a_new_unit_and_none_for_one_already_in_progress():
    found = occupied([on_branch("a/1")], locks=locks("a/1"), leases=(), now=NOW, lane={"a/1"})
    limits = Limits(stacks=1, emergency_extra=1)

    assert free(found, limits, key()) == 0
    assert free(found, limits, key(), new=False) == 1


def test_a_paused_lane_unit_with_no_run_holds_a_lane_place_and_no_worker():
    limits = Limits(stacks=1, emergency_extra=1)
    alone = occupied([paused_unit("l/1")], locks=(), leases=(), now=NOW, lane={"l/1"})
    beside = occupied(
        [paused_unit("l/1"), on_branch("r/1")], locks=locks("r/1"), leases=(), now=NOW, lane={"l/1"}
    )

    assert alone.emergency == {key(): 1}
    assert alone.workers == {}
    assert emergency_free(alone, limits, key()) == 0
    assert free(alone, limits, key(), new=False) == 1
    assert free(beside, limits, key(), new=False) == 0


def test_a_paused_lane_unit_a_run_holds_is_taken_off_the_workers_of_a_unit_in_progress():
    found = occupied([paused_unit("l/1")], locks=locks("l/1"), leases=(), now=NOW, lane={"l/1"})

    assert found.lane_workers == {key(): 1}
    assert free(found, Limits(stacks=1, emergency_extra=1), key(), new=False) == 1


def test_a_paused_unit_holds_a_place_and_no_worker():
    found = occupied([paused_unit("a/1")], locks=(), leases=(), now=NOW)

    assert found.projects == {key(): 1}
    assert found.workers == {}
    assert free(found, Limits(stacks=1), key()) == 1


def test_a_paused_unit_a_run_has_taken_up_holds_a_worker_by_its_marker():
    resuming = paused_unit("a/1").model_copy(
        update={"starting": Starting(worker="w1", until=NOW + timedelta(minutes=5))}
    )

    found = occupied([resuming], locks=(), leases=(), now=NOW)

    assert found.workers == {key(): 1}
    assert free(found, Limits(stacks=1), key(), new=False) == 0


def test_a_paused_unit_a_run_has_taken_up_holds_a_worker_by_its_lock():
    found = occupied([paused_unit("a/1")], locks=locks("a/1"), leases=(), now=NOW)

    assert found.projects == {key(): 1}
    assert found.workers == {key(): 1}


def test_a_paused_unit_a_known_run_holds_is_a_worker():
    found = occupied([paused_unit("a/1")], locks=(), leases=(), held={"a/1"}, now=NOW)

    assert found.workers == {key(): 1}


def test_with_the_units_in_progress_reached_a_paused_unit_keeps_a_new_one_out():
    found = occupied([paused_unit("a/1")], locks=(), leases=(), now=NOW)
    limits = Limits(stacks=3, in_progress=1)

    assert free(found, limits, key()) == 0
    assert free(found, limits, key(), new=False) == 3


def test_the_units_in_progress_of_one_project_do_not_count_against_another():
    found = occupied([paused_unit("a/1")], locks=(), leases=(), now=NOW)

    assert free(found, Limits(stacks=3, in_progress=1), key("platform")) == 1


def test_an_accounts_own_limit_caps_the_free_slots():
    units = [on_branch("a/1", repo="platform"), on_branch("b/1", repo="platform")]
    found = occupied(
        units, locks=locks("a/1", "b/1"), leases=(), now=NOW, account_of=lambda _: "kit"
    )

    assert free(found, Limits(stacks=5, accounts={"kit": 3}), key("app"), "kit") == 1
    assert free(found, Limits(stacks=5, accounts={"kit": 2}), key("app"), "kit") == 0


def test_the_lane_has_the_places_its_extra_leaves():
    found = occupied([on_branch("a/1")], locks=locks("a/1"), leases=(), now=NOW, lane={"a/1"})
    limits = Limits(stacks=1, emergency_extra=2)

    assert emergency_free(found, limits, key()) == 1
    assert emergency_free(found, Limits(stacks=1), key()) == 0
