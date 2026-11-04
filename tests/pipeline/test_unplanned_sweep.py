"""Which `unplanned` units may be swept (spec: unplanned-sweep): five conditions, all required,
the first one that fails named, over stores built in memory. Nothing here removes a unit."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import MERGED, PLANNED, UnitState
from agent_build_kit.pipeline.unplanned_sweep import Reference, Verdict, eligibility
from tests.factories import stored_unit

PASS_STARTED = datetime(2030, 1, 10, 12, 0, tzinfo=UTC)
DEMOTED = PASS_STARTED - timedelta(hours=1)
CHANGE = "c"


def tomb(uid: str, groups: tuple[int, ...] = (2,), *, at: datetime = DEMOTED, **fields: Any):
    """An `unplanned` unit of change `c`, demoted at `at`."""
    fields = {
        "change": CHANGE,
        "history": ({"state": "unplanned", "at": at.isoformat()},),
    } | fields
    return stored_unit(uid, groups=groups, state=UnitState.UNPLANNED, **fields)


def live(uid: str = "c/1", groups: tuple[int, ...] = (1, 2), **fields: Any) -> StoredUnit:
    return stored_unit(uid, change=CHANGE, groups=groups, state=PLANNED, **fields)


def verdicts(
    *units: StoredUnit,
    active: Collection[str] = (CHANGE,),
    archived: Collection[str] = (),
    tracker: datetime | None | str = "none",
) -> dict[str, Verdict]:
    """The sweep's verdicts; `tracker` is "none" for no tracker configured, else the time of its
    last successful reconcile (None: it cannot be read)."""
    configured = tracker != "none"
    return eligibility(
        list(units),
        active_changes=set(active),
        archived_changes=set(archived),
        pass_started=PASS_STARTED,
        tracker_configured=configured,
        tracker_reconciled=tracker if isinstance(tracker, datetime) else None,
    )


def test_a_tombstone_with_nothing_attached_is_eligible() -> None:
    found = verdicts(live(), tomb("c/3"))

    assert found["c/3"] == Verdict(unit="c/3", eligible=True)


@pytest.mark.parametrize(
    "work",
    [{"branch": "spec/c/3"}, {"pr": 12}, {"pushed": "a" * 40}, {"approved": "b" * 40}],
    ids=["branch", "pull-request", "push", "approval"],
)
def test_a_tombstone_that_holds_work_is_kept_and_says_so(work: dict[str, Any]) -> None:
    found = verdicts(live(), tomb("c/3", **work))

    assert not found["c/3"].eligible
    assert "work" in found["c/3"].reason


def test_a_unit_in_any_other_state_is_never_considered() -> None:
    merged = stored_unit("c/4", change=CHANGE, groups=(4,), state=MERGED)

    found = verdicts(live(), merged, tomb("c/3"))

    assert set(found) == {"c/3"}


def test_a_reference_with_nothing_to_repoint_to_keeps_the_tombstone() -> None:
    found = verdicts(live(depends_on=("c/3",)), tomb("c/3"))

    assert not found["c/3"].eligible
    assert "referenced" in found["c/3"].reason and "c/1" in found["c/3"].reason


@pytest.mark.parametrize(
    "field", ["depends_on", "needs", "merge_needs", "waited_on", "superseded_by"]
)
def test_a_reference_from_a_live_unit_is_reported_for_repointing_to_the_successors(
    field: str,
) -> None:
    successor = live("c/5", groups=(2,))

    fields: dict[str, Any] = {field: ("c/3",)}
    found = verdicts(live(**fields), successor, tomb("c/3", superseded_by=("c/5",)))

    assert found["c/3"].eligible
    assert found["c/3"].repoint == (Reference(referrer="c/1", field=field),)
    assert found["c/3"].successors == ("c/5",)


def test_groups_that_no_live_unit_carries_keep_the_tombstone_of_a_live_change() -> None:
    found = verdicts(live(groups=(1,)), tomb("c/3", groups=(5,)))

    assert not found["c/3"].eligible
    assert "carried" in found["c/3"].reason


def test_a_change_that_is_gone_or_archived_needs_no_carrier() -> None:
    found = verdicts(live(groups=(1,)), tomb("c/3", groups=(5,)), active=())

    assert found["c/3"].eligible


def test_a_tombstone_demoted_in_this_pass_is_left_for_the_readers_of_this_pass() -> None:
    found = verdicts(live(), tomb("c/3", at=PASS_STARTED + timedelta(seconds=1)))

    assert not found["c/3"].eligible
    assert "pass" in found["c/3"].reason


@pytest.mark.parametrize(
    ("reconciled", "eligible"),
    [
        (DEMOTED - timedelta(minutes=5), False),
        (DEMOTED, False),
        (DEMOTED + timedelta(minutes=5), True),
        (None, False),
    ],
    ids=["before", "at", "after", "unknown"],
)
def test_a_tracker_must_have_reconciled_since_the_demotion(
    reconciled: datetime | None, eligible: bool
) -> None:
    found = verdicts(live(), tomb("c/3"), tracker=reconciled)

    assert found["c/3"].eligible is eligible
    if not eligible:
        assert "tracker" in found["c/3"].reason


def test_no_tracker_means_the_condition_does_not_apply() -> None:
    assert verdicts(live(), tomb("c/3"), tracker="none")["c/3"].eligible


def test_the_last_unit_of_a_live_change_is_kept() -> None:
    found = verdicts(tomb("c/3", groups=()))

    assert not found["c/3"].eligible
    assert "last" in found["c/3"].reason


def test_the_last_unit_of_an_archived_change_may_go() -> None:
    assert verdicts(tomb("c/3", groups=(1,)), active=())["c/3"].eligible


def test_a_chain_of_two_tombstones_goes_together_once_each_is_eligible() -> None:
    first = tomb("c/3", superseded_by=("c/4",))
    second = tomb("c/4", superseded_by=("c/1",))

    found = verdicts(live(), first, second)

    assert found["c/3"].eligible and found["c/4"].eligible
    assert found["c/4"].repoint == (), "the reference from the other tombstone goes with it"


def test_a_chain_waits_when_one_of_the_two_is_not_eligible() -> None:
    first = tomb("c/3", superseded_by=("c/4",))
    second = tomb("c/4", superseded_by=("c/1",), pr=9)

    found = verdicts(live(), first, second)

    assert found["c/3"].eligible
    assert found["c/3"].repoint == () and not found["c/4"].eligible


def test_a_change_whose_every_unit_is_a_tombstone_keeps_them_all() -> None:
    found = verdicts(tomb("c/3", groups=()), tomb("c/4", groups=()))

    assert not found["c/3"].eligible and not found["c/4"].eligible
    assert "last" in found["c/3"].reason


def test_the_first_failed_condition_is_the_one_named() -> None:
    found = verdicts(live(depends_on=("c/3",)), tomb("c/3", branch="spec/c/3", groups=(5,)))

    assert "work" in found["c/3"].reason


def test_a_stamp_without_an_offset_is_read_as_utc_and_does_not_raise() -> None:
    naive = tomb("c/3", at=DEMOTED.replace(tzinfo=None) - timedelta(hours=1))

    assert verdicts(live(), naive)["c/3"].eligible


def test_a_demotion_time_that_cannot_be_read_keeps_the_unit() -> None:
    unreadable = tomb("c/3", history=({"state": "unplanned", "at": "not a time"},))
    missing = tomb("c/4", history=())

    found = verdicts(live(), unreadable, missing)

    assert not found["c/3"].eligible and "demoted" in found["c/3"].reason
    assert not found["c/4"].eligible and "demoted" in found["c/4"].reason


def test_a_reference_is_repointed_past_a_successor_that_goes_too() -> None:
    first = tomb("c/3", superseded_by=("c/4",))
    second = tomb("c/4", superseded_by=("c/5",))

    found = verdicts(live(depends_on=("c/3",)), live("c/5", groups=(2,)), first, second)

    assert found["c/3"].eligible and found["c/4"].eligible
    assert found["c/3"].successors == ("c/5",)


def test_a_unit_kept_by_the_last_unit_rule_keeps_what_it_references() -> None:
    other = tomb("x/3", groups=(), depends_on=("c/3",), change="x")
    named = tomb("c/3", groups=(2,))

    found = verdicts(live(), other, named, active=("c", "x"))

    assert not found["x/3"].eligible
    assert not found["c/3"].eligible and "x/3" in found["c/3"].reason


def test_an_archived_change_keeps_a_tombstone_whose_groups_no_live_unit_carries() -> None:
    kept = verdicts(live(groups=(1,)), tomb("c/3", groups=(2,)), active=(), archived=(CHANGE,))

    assert not kept["c/3"].eligible and "carried" in kept["c/3"].reason


def test_an_archived_change_sweeps_a_tombstone_a_live_unit_carries() -> None:
    found = verdicts(live(groups=(1, 2)), tomb("c/3", groups=(2,)), active=(), archived=(CHANGE,))

    assert found["c/3"].eligible


def test_a_successor_that_is_not_in_the_store_leaves_a_reference_unrepointable() -> None:
    found = verdicts(live(depends_on=("c/3",)), tomb("c/3", superseded_by=("c/9",)))

    assert not found["c/3"].eligible
    assert "referenced" in found["c/3"].reason
