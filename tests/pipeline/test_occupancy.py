"""Occupancy is one pure function over live locks, leases and `starting` markers, and the free
slots are read from it against the limits."""

from datetime import timedelta

from agent_build_kit.pipeline.occupancy import Limits, Occupancy, emergency_free, free, occupied
from agent_build_kit.pipeline.unit_store import Starting
from agent_build_kit.pipeline.units import ProjectKey
from tests.factories import new_unit
from tests.fake_clock import START

APP = ProjectKey(repo="app")
PLATFORM = ProjectKey(repo="platform")
LIMITS = Limits(stacks=2, emergency=1, in_progress=5)


def built(uid: str, repo: str = "app", **fields: object):
    return new_unit(uid, repo=repo, branch=f"spec/{uid}", **fields)


def test_live_locks_count_per_project() -> None:
    units = [built("a/1"), built("b/1"), built("c/1", repo="platform"), built("d/1")]

    found = occupied(units, locks={"spec/a/1", "spec/b/1", "spec/c/1"}, leases=(), now=START)

    assert found.projects == {APP: 2, PLATFORM: 1}


def test_a_lease_occupies_a_slot() -> None:
    found = occupied([built("a/1")], locks=(), leases={"a/1"}, now=START)

    assert found.projects == {APP: 1}


def test_an_unexpired_starting_marker_occupies_a_slot() -> None:
    marker = Starting(worker="w1", until=START + timedelta(seconds=30))

    found = occupied([built("a/1", starting=marker)], locks=(), leases=(), now=START)

    assert found.projects == {APP: 1}


def test_an_expired_starting_marker_is_ignored() -> None:
    marker = Starting(worker="w1", until=START - timedelta(seconds=1))

    found = occupied([built("a/1", starting=marker)], locks=(), leases=(), now=START)

    assert found.projects == {}


def test_a_unit_with_a_lock_a_lease_and_a_marker_counts_once() -> None:
    marker = Starting(worker="w1", until=START + timedelta(seconds=30))

    found = occupied([built("a/1", starting=marker)], locks={"spec/a/1"}, leases={"a/1"}, now=START)

    assert found.projects == {APP: 1}


def test_accounts_count_by_the_unit_s_account() -> None:
    units = [built("a/1"), built("b/1"), built("c/1", repo="platform")]

    found = occupied(
        units,
        locks={"spec/a/1", "spec/b/1", "spec/c/1"},
        leases=(),
        now=START,
        account_of=lambda unit: "kit" if unit.repo == "app" else "",
    )

    assert found.accounts == {"kit": 2, "": 1}


def test_the_emergency_lane_counts_apart_and_takes_no_project_slot() -> None:
    units = [built("a/1"), built("urgent/1")]

    found = occupied(
        units, locks={"spec/a/1", "spec/urgent/1"}, leases=(), now=START, lane={"urgent/1"}
    )

    assert found.emergency == 1
    assert found.projects == {APP: 1}


def test_free_slots_are_the_stacks_less_the_project_s_occupancy() -> None:
    taken = Occupancy(projects={APP: 1, PLATFORM: 2})

    assert free(taken, LIMITS, project=APP) == 1
    assert free(taken, LIMITS, project=PLATFORM) == 0
    assert free(Occupancy(), LIMITS, project=APP) == 2


def test_free_slots_never_go_below_zero() -> None:
    assert free(Occupancy(projects={APP: 3}), LIMITS, project=APP) == 0


def test_an_account_s_own_limit_can_be_the_smaller() -> None:
    limits = Limits(stacks=4, emergency=1, in_progress=5, accounts={"kit": 1})
    taken = Occupancy(projects={APP: 1}, accounts={"kit": 1})

    assert free(taken, limits, project=APP, account="kit") == 0
    assert free(taken, limits, project=APP, account="") == 3


def test_an_account_without_a_limit_gets_the_in_progress_limit() -> None:
    limits = Limits(stacks=9, emergency=1, in_progress=2)

    assert free(Occupancy(accounts={"kit": 1}), limits, project=APP, account="kit") == 1


def test_the_emergency_lane_s_free_places() -> None:
    assert emergency_free(Occupancy(emergency=0), LIMITS) == 1
    assert emergency_free(Occupancy(emergency=1), LIMITS) == 0
    assert emergency_free(Occupancy(emergency=2), LIMITS) == 0
