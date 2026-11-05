"""A late check's local run holds no claim while it waits (spec: merged-waits-for-ci).

The unit's claim is taken to read the unit before the run and to record the result, and is free
in between, so another handler (or a person's `abk settle --accept`) can take it. A unit that is
no longer settling at the record step is left as it is: the late result changes nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import Check, CheckStatus, CommitChecks, commit_checks_of
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Pull, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import MERGED, PLANNED, SETTLING
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_lock
from tests.factories import stored_unit

SHA = "abc123"
LOG = "FAILED tests/test_marker.py::test_registers - AssertionError"
MERGED_AT = datetime(2026, 10, 27, 11, 43, tzinfo=UTC)
PERSON = "accepted as merged by a person: the runner was retired"


def settling(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")
    store.set_pulls(
        "add-marker/1",
        (Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha=SHA),),
    )
    store.set_merge_record("add-marker/1", SHA, None)
    return store


def red() -> PullRequest:
    return PullRequest(
        number=4,
        head="spec/add-marker/1",
        base="main",
        state="merged",
        checks=(Check(name="test", status=CheckStatus.FAILED),),
    )


def late_check(
    store: UnitStore,
    base_passes,
    claim,
) -> bool:
    return events.on_late_check(
        4,
        repo="app",
        pull=red(),
        store=store,
        fetch_checks=lambda pull: LOG,
        base_passes=base_passes,
        claim=claim,
        merge_record=lambda unit: (SHA, 9),
        log=lambda message: None,
    )


def test_while_the_run_waits_the_unit_s_claim_is_free_for_another_handler(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    locks = tmp_path / "locks"
    claim = events.build_claim(locks)
    taken: list[str] = []

    def base_passes(unit: StoredUnit, logs: str) -> bool:
        with claim(unit):  # another handler, while the late check's run waits
            taken.append(unit.id)
        return False

    assert late_check(store, base_passes, claim) is True

    assert taken == ["add-marker/1"]
    assert store.get("add-marker/1").state == PLANNED


def test_the_result_is_recorded_under_the_claim_and_the_run_is_outside_it(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    steps: list[str] = []

    @contextmanager
    def claim(unit: StoredUnit) -> Generator[None]:
        steps.append("claim")
        yield
        steps.append(f"release {store.get(unit.id).state}")

    def base_passes(unit: StoredUnit, logs: str) -> bool:
        steps.append("run")
        return False

    late_check(store, base_passes, claim)

    assert steps == ["claim", "release settling", "run", "claim", "release planned"]


@pytest.mark.parametrize("passes", [True, False], ids=["passes-on-the-base", "fails-there"])
def test_a_unit_accepted_while_the_run_waited_is_left_as_the_person_recorded_it(
    tmp_path: Path, passes: bool
) -> None:
    store = settling(tmp_path)
    claim = events.build_claim(tmp_path / "locks")

    def base_passes(unit: StoredUnit, logs: str) -> bool:
        with claim(unit):  # `abk settle --accept`, while the run waits
            events.settle_merged(store, store.get(unit.id), None, note=PERSON)
        return passes

    late_check(store, base_passes, claim)

    unit = store.get("add-marker/1")
    assert unit.state == MERGED
    assert unit.history[-1]["note"] == PERSON
    assert unit.feedback == ""
    assert unit.branch == "spec/add-marker/1"


def test_a_unit_whose_claim_is_held_before_the_run_is_left_for_a_later_poll(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    locks = tmp_path / "locks"
    ran: list[str] = []

    with branch_lock("spec/add-marker/1", root=locks):
        handled = late_check(
            store, lambda unit, logs: ran.append(unit.id) or True, events.build_claim(locks)
        )

    assert handled is False
    assert ran == []
    assert store.get("add-marker/1").state == SETTLING


def test_a_second_late_check_of_the_same_unit_does_not_run_while_the_first_waits(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    claim = events.build_claim(tmp_path / "locks")
    turn = events.build_late_check_turn(tmp_path / "locks")
    second: list[bool] = []
    runs: list[str] = []
    waiting = threading.Event()
    release = threading.Event()

    def blocked(unit: StoredUnit, logs: str) -> bool:
        runs.append(unit.id)
        waiting.set()
        release.wait(timeout=20)
        return False

    def first() -> None:
        events.on_late_check(
            4,
            repo="app",
            pull=red(),
            store=store,
            fetch_checks=lambda pull: LOG,
            base_passes=blocked,
            claim=claim,
            late_turn=turn,
            log=lambda message: None,
        )

    thread = threading.Thread(target=first, daemon=True)
    thread.start()
    try:
        assert waiting.wait(timeout=20)
        second.append(
            events.on_late_check(
                4,
                repo="app",
                pull=red(),
                store=store,
                fetch_checks=lambda pull: LOG,
                base_passes=blocked,
                claim=claim,
                late_turn=turn,
                log=lambda message: None,
            )
        )
    finally:
        release.set()
        thread.join(timeout=20)

    assert second == [False], "the second is left for a later poll"
    assert runs == ["add-marker/1"]
    with turn(store.get("add-marker/1")):
        pass  # free again once the first has ended


# --- review: the record step waits a little for the claim, and the merge commit's checks ----


class BusyFor:
    """A claim that is free for the read and then busy for the next `busy` attempts."""

    def __init__(self, busy: int) -> None:
        self.busy = busy
        self.calls = 0

    @contextmanager
    def __call__(self, unit: StoredUnit) -> Generator[None]:
        self.calls += 1
        if 1 < self.calls <= 1 + self.busy:
            raise BranchBusy("spec/add-marker/1 is held by another handler")
        yield


def run_with(store: UnitStore, claim, sleeps: list[float], said: list[str]) -> bool:
    return events.on_late_check(
        4,
        repo="app",
        pull=red(),
        store=store,
        fetch_checks=lambda pull: LOG,
        base_passes=lambda unit, logs: False,
        claim=claim,
        sleep=sleeps.append,
        log=said.append,
    )


def test_the_record_step_waits_briefly_for_a_busy_claim_and_keeps_the_result(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    sleeps: list[float] = []

    assert run_with(store, BusyFor(2), sleeps, []) is True

    assert store.get("add-marker/1").state == PLANNED
    assert len(sleeps) == 2


def test_a_claim_busy_past_the_retries_is_left_for_a_later_poll_and_says_why(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    sleeps: list[float] = []
    said: list[str] = []

    assert run_with(store, BusyFor(100), sleeps, said) is False

    assert store.get("add-marker/1").state == SETTLING
    assert len(sleeps) == events.RECORD_TRIES - 1
    assert not any("being built" in line for line in said)
    assert any("late check #4" in line and "could not be recorded" in line for line in said)


def test_the_merge_commit_s_checks_are_read_and_settled_under_the_claim_with_no_run(
    tmp_path: Path,
) -> None:
    store = settling(tmp_path)
    steps: list[str] = []
    held = False

    @contextmanager
    def claim(unit: StoredUnit) -> Generator[None]:
        nonlocal held
        held = True
        steps.append("claim")
        yield
        held = False
        steps.append(f"release {store.get(unit.id).state}")

    def base_checks(unit: StoredUnit, sha: str, branch: str) -> CommitChecks:
        steps.append(f"read under claim: {held}")
        return commit_checks_of([Check(name="test", status=CheckStatus.PASSED)])

    events.on_late_check(
        4,
        repo="app",
        pull=red().model_copy(update={"merge_commit": SHA}),
        store=store,
        base_passes=lambda unit, logs: steps.append("run") is None,
        base_checks=base_checks,
        claim=claim,
        log=lambda message: None,
    )

    assert steps == ["claim", "read under claim: True", "release merged"]
