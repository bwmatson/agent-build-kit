"""Merged changes sorted into trusted, pending, fixed, reverted and unchecked, and their cost
(spec: trusted-change-cost). The units are the store's, the costs a mapping and the revert
lookup a fake that answers from the unit and the bound it is given."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.pipeline.trusted_cost import (
    RevertLookup,
    TrustedChanges,
    Verdict,
    sort_changes,
)
from agent_build_kit.pipeline.unit_store import Pull, StoredUnit
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
DAYS = 30
FEATURE = "feature"


def stamp(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def merged(change: str = FEATURE, days_ago: float = 45, number: int = 1, **fields) -> StoredUnit:
    history = ({"state": "merged", "at": stamp(days_ago), "cause": "merged"},)
    return stored_unit(
        f"{change}/{number}",
        change=change,
        state=UnitState.MERGED,
        history=fields.pop("history", history),
        **fields,
    )


def fix_unit(
    began_days_after_merge: float,
    *,
    change: str = "fix-flaky-x",
    state: UnitState = UnitState.RUNNING,
) -> StoredUnit:
    began = NOW - timedelta(days=45) + timedelta(days=began_days_after_merge)
    return stored_unit(
        f"{change}/1",
        change=change,
        state=state,
        needs=(f"{FEATURE}/1",),
        history=({"state": "running", "at": began.isoformat(), "cause": "started"},),
    )


def nothing_found(unit: StoredUnit, until: datetime) -> bool | None:
    return False


def cannot_search(unit: StoredUnit, until: datetime) -> bool | None:
    return None


def reverted_after(days: float) -> RevertLookup:
    """A trunk holding a revert `days` days after the merge of the unit it is asked about: found
    only when the search is bounded no earlier than the revert."""

    def lookup(unit: StoredUnit, until: datetime) -> bool | None:
        merge = max(datetime.fromisoformat(e["at"]) for e in unit.history if e["state"] == "merged")
        return until >= merge + timedelta(days=days)

    return lookup


def answering(answers: dict[str, bool | None]) -> RevertLookup:
    return lambda unit, until: answers[unit.id]


def sort(
    units: list[StoredUnit],
    lookup: RevertLookup = nothing_found,
    costs: dict[str, float | None] | None = None,
) -> TrustedChanges:
    return sort_changes(units, costs or {}, lookup, now=NOW, days=DAYS)


def verdict_of(report: TrustedChanges, change: str = FEATURE) -> Verdict | None:
    return next((c.verdict for c in report.changes if c.change == change), None)


LATE_FAILURE = ({"state": "merged", "at": stamp(45), "cause": "merged"},) + (
    {"state": "in_review", "at": stamp(40), "cause": "late_failure"},
)

Case = tuple[Callable[[], list[StoredUnit]], RevertLookup, Verdict | None]

VERDICTS: dict[str, Case] = {
    "trusted at 45 days": (lambda: [merged()], nothing_found, Verdict.TRUSTED),
    "pending at 10 days": (lambda: [merged(days_ago=10)], nothing_found, Verdict.PENDING),
    "pending at 29 days 23 hours": (
        lambda: [merged(days_ago=30 - 1 / 24)],
        nothing_found,
        Verdict.PENDING,
    ),
    "fixed by a late failure": (
        lambda: [merged(history=LATE_FAILURE)],
        nothing_found,
        Verdict.FIXED,
    ),
    "fixed by a late-fix pull request": (
        lambda: [merged(pulls=(Pull(number=7, role="late-fix"),))],
        nothing_found,
        Verdict.FIXED,
    ),
    "fixed by a fix unit that began 3 days after": (
        lambda: [merged(), fix_unit(3)],
        nothing_found,
        Verdict.FIXED,
    ),
    "fixed by a hotfix unit that began 3 days after": (
        lambda: [merged(), fix_unit(3, change="hotfix-x")],
        nothing_found,
        Verdict.FIXED,
    ),
    "trusted when the fix unit began 40 days after": (
        lambda: [merged(), fix_unit(40)],
        nothing_found,
        Verdict.TRUSTED,
    ),
    "trusted when the fix unit began 1 day before the merge": (
        lambda: [merged(), fix_unit(-1)],
        nothing_found,
        Verdict.TRUSTED,
    ),
    "trusted when the listing unit's change is not a fix": (
        lambda: [merged(), fix_unit(3, change="tidy-x")],
        nothing_found,
        Verdict.TRUSTED,
    ),
    "trusted when the fix unit is retired": (
        lambda: [merged(), fix_unit(3, state=UnitState.RETIRED)],
        nothing_found,
        Verdict.TRUSTED,
    ),
    "reverted 5 days after the merge": (
        lambda: [merged()],
        reverted_after(5),
        Verdict.REVERTED,
    ),
    "trusted when the revert is found only by a later bound": (
        lambda: [merged()],
        reverted_after(31),
        Verdict.TRUSTED,
    ),
    "unchecked when the search cannot be made": (
        lambda: [merged()],
        cannot_search,
        Verdict.UNCHECKED,
    ),
    "unchecked when one unit answers false and another none": (
        lambda: [merged(number=1), merged(number=2)],
        answering({"feature/1": False, "feature/2": None}),
        Verdict.UNCHECKED,
    ),
    "not listed while a unit is in review": (
        lambda: [merged(number=1), stored_unit("feature/2", change=FEATURE, state="in_review")],
        nothing_found,
        None,
    ),
}


@pytest.mark.parametrize("units, lookup, expected", VERDICTS.values(), ids=VERDICTS.keys())
def test_a_merged_change_gets_the_verdict_its_history_and_the_trunk_give(
    units: Callable[[], list[StoredUnit]], lookup: RevertLookup, expected: Verdict | None
) -> None:
    assert verdict_of(sort(units(), lookup)) == expected


def test_a_change_with_a_revert_and_a_late_failure_is_fixed_and_lists_both_reasons() -> None:
    report = sort([merged(history=LATE_FAILURE)], reverted_after(5))

    judged = next(c for c in report.changes if c.change == FEATURE)
    assert judged.verdict == Verdict.FIXED
    assert len(judged.reasons) == 2


def test_the_lookup_is_given_the_bound_of_the_units_own_merge_plus_days() -> None:
    asked: list[datetime] = []

    def lookup(unit: StoredUnit, until: datetime) -> bool | None:
        asked.append(until)
        return False

    sort([merged()], lookup)

    assert asked == [NOW - timedelta(days=45) + timedelta(days=DAYS)]


def test_a_change_costs_what_was_recorded_and_one_with_none_is_out_of_the_mean() -> None:
    units = [merged(FEATURE, 45), merged("other", 40)]

    report = sort(units, costs={FEATURE: 7.0, "other": None})

    cost = {c.change: c.cost for c in report.changes}
    assert cost == {FEATURE: 7.0, "other": None}
    assert report.latest.cost_per_trusted_change == 7.0
    assert report.latest.trusted == 1
    assert report.latest.uncosted == 1


def test_changes_fall_in_the_window_of_their_merge_date_and_only_trusted_ones_count() -> None:
    units = [
        merged("t35", 35),
        merged("t55", 55),
        merged("uncosted", 50),
        merged(
            "fixed", 45, history=({"state": "merged", "at": stamp(45), "cause": "late_failure"},)
        ),
        merged("unchecked", 40),
        merged("pending", 10),
        merged("t65", 65),
        merged("t85", 85),
    ]
    costs: dict[str, float | None] = {
        "t35": 10.0,
        "t55": 20.0,
        "uncosted": None,
        "fixed": 100.0,
        "unchecked": 5.0,
        "pending": 50.0,
        "t65": 30.0,
        "t85": 50.0,
    }
    lookup = lambda unit, until: None if unit.change == "unchecked" else False  # noqa: E731

    report = sort(units, lookup, costs)

    assert report.latest.trusted == 2
    assert report.latest.uncosted == 1
    assert report.latest.cost == 30.0
    assert report.latest.cost_per_trusted_change == 15.0
    assert report.previous.trusted == 2
    assert report.previous.cost_per_trusted_change == 40.0
    assert report.pending_count == 1
    assert report.pending_cost == 50.0
    assert report.unchecked == ("unchecked",)
