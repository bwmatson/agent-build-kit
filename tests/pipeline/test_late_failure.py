"""A failed check of a merged pull request is run on the default branch (spec: merged-waits-for-ci).

Its failing tests pass there: the unit is merged and the failure is recorded as fixed on the base.
They fail there: the same unit goes back to `planned` for a late fix on a new branch with the
check's log in its prompt. After two late fixes a further failure holds the unit for a person.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Pull, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, MERGED, PLANNED, SETTLING
from tests.factories import stored_unit

SHA = "abc123"
TICK = 9
LOG = "FAILED tests/test_marker.py::test_registers - AssertionError"
MERGED_AT = datetime(2026, 10, 27, 11, 43, tzinfo=UTC)


def original() -> Pull:
    return Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha=SHA)


def late_fix(number: int, k: int) -> Pull:
    return Pull(
        number=number,
        branch=f"spec/add-marker/1-fix{k}",
        role="late-fix",
        merged_at=MERGED_AT,
        merge_sha=f"{SHA}{k}",
    )


class Base:
    """What running the failing tests on the default branch said, and what it was asked."""

    def __init__(self, passes: bool) -> None:
        self.passes = passes
        self.asked: list[tuple[str, str]] = []

    def __call__(self, unit: StoredUnit, log: str) -> bool:
        self.asked.append((unit.id, log))
        return self.passes


def settling(tmp_path: Path, pulls: tuple[Pull, ...] = ()) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    last = (pulls or (original(),))[-1]
    store.set_state("add-marker/1", SETTLING, pr=last.number, branch=last.branch)
    store.set_pulls("add-marker/1", pulls or (original(),))
    store.set_merge_record("add-marker/1", last.merge_sha, None)
    return store


def red() -> PullRequest:
    return PullRequest(
        number=4,
        head="spec/add-marker/1",
        base="main",
        state="merged",
        checks=(Check(name="test", status=CheckStatus.FAILED),),
    )


def late_check(store: UnitStore, base: Base, pr: int = 4) -> bool:
    dispatch = events.build_dispatch(
        store,
        restack=lambda **k: None,
        merge_record=lambda unit: (SHA, TICK),
        fetch_checks=lambda repo, pull: LOG,
        base_passes=base,
        log=lambda m: None,
    )
    return dispatch("late_check", pr, repo="app", pull=red())


def test_tests_that_pass_on_the_base_make_the_unit_merged_and_the_failure_fixed_there(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    base = Base(passes=True)

    assert late_check(store, base) is True

    unit = store.get("add-marker/1")
    assert unit.state == MERGED
    assert unit.merged_tick == TICK
    assert base.asked == [("add-marker/1", LOG)]
    note = unit.history[-1]["note"]
    assert "fixed on the base" in note
    assert "test" in note
    assert "tests/test_marker.py::test_registers" in note


def test_tests_that_fail_on_the_base_send_the_same_unit_to_a_late_fix_branch(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    before = store.get("add-marker/1")

    assert late_check(store, Base(passes=False)) is True

    unit = store.get("add-marker/1")
    assert unit.id == "add-marker/1"
    assert unit.state == PLANNED
    assert unit.cause == "late_failure"
    assert unit.branch == "spec/add-marker/1-fix1"
    assert unit.pr is None
    assert unit.groups == before.groups
    assert unit.merged_tick is None
    assert [p.number for p in unit.pulls] == [4]


def test_the_late_fix_prompt_carries_the_check_log_and_the_merge_note(tmp_path: Path) -> None:
    store = settling(tmp_path)

    late_check(store, Base(passes=False))

    feedback = store.get("add-marker/1").feedback
    assert LOG in feedback
    assert "merged while its check was failing" in feedback
    assert "from the default branch" in feedback


def test_a_second_late_fix_is_numbered_after_the_first(tmp_path: Path) -> None:
    store = settling(tmp_path, (original(), late_fix(9, 1)))

    late_check(store, Base(passes=False), pr=9)

    assert store.get("add-marker/1").branch == "spec/add-marker/1-fix2"
    assert store.get("add-marker/1").state == PLANNED


def test_after_two_late_fixes_a_further_failure_holds_the_unit_for_a_person(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path, (original(), late_fix(9, 1), late_fix(12, 2)))

    late_check(store, Base(passes=False), pr=12)

    unit = store.get("add-marker/1")
    assert unit.state == HELD
    assert unit.branch == "spec/add-marker/1-fix2"
    assert [p.number for p in unit.pulls] == [4, 9, 12]


def test_a_unit_with_its_late_fix_open_takes_no_further_late_check(tmp_path: Path) -> None:
    """One late fix is open at a time: the unit is `planned`, not settling, until it is merged."""
    store = settling(tmp_path)
    late_check(store, Base(passes=False))
    after_first = store.get("add-marker/1")
    base = Base(passes=False)

    late_check(store, base)

    assert base.asked == []
    assert store.get("add-marker/1").branch == after_first.branch
    assert store.get("add-marker/1").state == PLANNED


@pytest.mark.parametrize("passes", [True, False])
def test_a_late_check_for_a_pull_request_with_no_unit_changes_nothing(
    tmp_path: Path, passes: bool
) -> None:
    store = settling(tmp_path)
    base = Base(passes=passes)

    assert late_check(store, base, pr=77) is True

    assert base.asked == []
    assert store.get("add-marker/1").state == SETTLING
