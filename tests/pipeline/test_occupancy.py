"""Occupancy is a pure function of plain data: live locks, leases, unexpired `starting` markers
and recorded usage pauses, counted per project, per account and in the emergency lane, then held
to the limits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_build_kit.pipeline.occupancy import Limits, emergency_free, free, occupied
from agent_build_kit.pipeline.unit_store import Starting
from agent_build_kit.pipeline.units import RUNNING, ProjectKey, Unit
from tests.factories import new_unit

NOW = datetime(2030, 1, 1, 12, tzinfo=UTC)


def key(repo: str = "app") -> ProjectKey:
    return ProjectKey(repo=repo)


def marked(uid: str, *, lapses: timedelta, repo: str = "app"):
    return new_unit(uid, repo=repo).model_copy(
        update={"starting": Starting(worker="w1", until=NOW + lapses)}
    )


def test_a_live_lock_a_live_lease_and_an_unexpired_marker_each_occupy_a_slot():
    units = [
        new_unit("a/1", branch="spec/a/1"),
        new_unit("b/1"),
        marked("c/1", lapses=timedelta(minutes=5)),
        new_unit("d/1"),
    ]

    found = occupied(units, locks={"spec/a/1"}, leases={"b/1"}, now=NOW)

    assert found.projects == {key(): 3}


def test_a_recorded_usage_pause_occupies_a_slot_with_no_lock_or_lease():
    paused = new_unit("a/1").model_copy(
        update={"state": RUNNING, "paused_until": NOW + timedelta(hours=1)}
    )
    idle = new_unit("b/1").model_copy(update={"state": RUNNING})

    found = occupied([paused, idle], locks=(), leases=(), now=NOW)

    assert found.projects == {key(): 1}


def test_an_expired_marker_occupies_nothing():
    found = occupied([marked("a/1", lapses=timedelta(seconds=-1))], locks=(), leases=(), now=NOW)

    assert found.projects.get(key(), 0) == 0


def test_a_unit_named_by_a_lock_a_lease_and_a_marker_is_counted_once():
    unit = marked("a/1", lapses=timedelta(minutes=5)).model_copy(update={"branch": "spec/a/1"})

    found = occupied([unit], locks={"spec/a/1"}, leases={"a/1"}, now=NOW)

    assert found.projects == {key(): 1}


def test_projects_are_counted_apart():
    units = [new_unit("a/1", repo="app"), new_unit("b/1", repo="platform")]

    found = occupied(units, locks=(), leases={"a/1", "b/1"}, now=NOW)

    assert found.projects == {key("app"): 1, key("platform"): 1}


def test_units_are_counted_under_their_accounts():
    units = [new_unit("a/1", repo="app"), new_unit("b/1", repo="platform"), new_unit("c/1")]

    def account_of(unit: Unit) -> str | None:
        return "kit" if unit.repo == "platform" else None

    found = occupied(units, locks=(), leases={"a/1", "b/1", "c/1"}, now=NOW, account_of=account_of)

    assert found.accounts == {None: 2, "kit": 1}


def test_the_emergency_lane_counts_the_occupying_units_it_holds():
    units = [new_unit("a/1"), new_unit("b/1"), new_unit("c/1")]

    found = occupied(units, locks=(), leases={"a/1", "b/1"}, now=NOW, lane={"b/1", "c/1"})

    assert found.emergency == {key(): 1}


def test_free_slots_are_the_workers_left_in_the_project():
    units = [new_unit("a/1"), new_unit("b/1", repo="platform")]
    found = occupied(units, locks=(), leases={"a/1", "b/1"}, now=NOW)

    limits = Limits(stacks=3)

    assert free(found, limits, key("app")) == 2
    assert free(found, limits, key("web")) == 3


def test_a_full_project_has_no_free_slot():
    found = occupied([new_unit("a/1")], locks=(), leases={"a/1"}, now=NOW)

    assert free(found, Limits(stacks=1), key()) == 0


def test_a_lane_unit_takes_no_worker_of_its_projects():
    found = occupied([new_unit("a/1")], locks=(), leases={"a/1"}, now=NOW, lane={"a/1"})

    assert free(found, Limits(stacks=1, emergency_extra=1), key()) == 1


def test_an_accounts_own_limit_caps_the_free_slots():
    units = [new_unit("a/1", repo="platform"), new_unit("b/1", repo="platform")]
    found = occupied(units, locks=(), leases={"a/1", "b/1"}, now=NOW, account_of=lambda _: "kit")

    assert free(found, Limits(stacks=5, accounts={"kit": 3}), key("app"), "kit") == 1
    assert free(found, Limits(stacks=5, accounts={"kit": 2}), key("app"), "kit") == 0


def test_the_lane_has_the_places_its_extra_leaves():
    found = occupied([new_unit("a/1")], locks=(), leases={"a/1"}, now=NOW, lane={"a/1"})
    limits = Limits(stacks=1, emergency_extra=2)

    assert emergency_free(found, limits, key()) == 1
    assert emergency_free(found, Limits(stacks=1), key()) == 0
