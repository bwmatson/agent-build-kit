"""A unit in review reads `checking` while its checks run.

The status is derived from the stored `in_review` state, the pull request's
checks as the last poll recorded them, and when the unit was last pushed; it is
never stored, and scheduling does not see it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.pr_poller import PrState, recorded_checks, state_path
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, in_progress, ready_units
from agent_build_kit.pipeline.vocabulary import (
    STATES,
    effective_state,
    state_label,
    state_label_names,
)
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import FakeClock, install
from tests.forges.stand_in import StandInForge, lookup

PR = 7
UID = "add-marker/1"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


def checks_of(*listed: CheckStatus) -> Callable[[StoredUnit], Sequence[Check]]:
    """A lookup answering the same checks for every pull request."""
    held = tuple(Check(name=f"check-{n}", status=status) for n, status in enumerate(listed))

    def lookup_checks(unit: StoredUnit) -> Sequence[Check]:
        return held

    return lookup_checks


def pushed(clock: FakeClock, *, ago: float, uid: str = UID) -> StoredUnit:
    """An in-review unit whose last push was `ago` seconds before now."""
    return stored_unit(
        uid,
        state="in_review",
        pr=PR,
        pushed="abc",
        pushed_at=clock.now() - timedelta(seconds=ago),
    )


def test_a_unit_with_a_pending_check_reads_checking(clock: FakeClock) -> None:
    unit = pushed(clock, ago=3600)

    shown = effective_state(
        unit, [unit], checks_of=checks_of(CheckStatus.PASSED, CheckStatus.PENDING)
    )

    assert shown == "checking"
    assert unit.state == IN_REVIEW, "derived, not stored"


def test_a_unit_whose_checks_all_passed_reads_in_review(clock: FakeClock) -> None:
    unit = pushed(clock, ago=5)

    assert effective_state(unit, [unit], checks_of=checks_of(CheckStatus.PASSED)) == IN_REVIEW
    # Checking is a real status here, not an absent one.
    assert effective_state(unit, [unit], checks_of=checks_of(CheckStatus.PENDING)) == "checking"


def test_a_unit_pushed_seconds_ago_with_no_checks_reads_checking(clock: FakeClock) -> None:
    unit = pushed(clock, ago=5)

    assert effective_state(unit, [unit], checks_of=checks_of()) == "checking"


def test_a_unit_with_no_checks_after_the_window_reads_in_review(clock: FakeClock) -> None:
    unit = pushed(clock, ago=3600)
    young = pushed(clock, ago=5, uid="add-marker/2")

    assert effective_state(unit, [unit], checks_of=checks_of()) == IN_REVIEW
    assert effective_state(young, [young], checks_of=checks_of()) == "checking"


def test_the_window_is_the_configured_number_of_seconds(tmp_path: Path, clock: FakeClock) -> None:
    make_installation(tmp_path, limits={"checks_register_seconds": 30})
    inside = pushed(clock, ago=20, uid="add-marker/1")
    outside = pushed(clock, ago=40, uid="add-marker/2")

    assert effective_state(inside, [inside], checks_of=checks_of()) == "checking"
    assert effective_state(outside, [outside], checks_of=checks_of()) == IN_REVIEW


def test_without_a_lookup_a_unit_in_review_reads_in_review(clock: FakeClock) -> None:
    unit = pushed(clock, ago=5)

    assert effective_state(unit, [unit]) == IN_REVIEW
    assert effective_state(unit, [unit], checks_of=checks_of(CheckStatus.PENDING)) == "checking"


def test_a_failed_check_beside_a_pending_one_does_not_read_checking(clock: FakeClock) -> None:
    """A failing check sends the unit back; until then it is simply in review."""
    unit = pushed(clock, ago=3600)

    failing = effective_state(
        unit, [unit], checks_of=checks_of(CheckStatus.FAILED, CheckStatus.PENDING)
    )

    assert failing == IN_REVIEW
    assert effective_state(unit, [unit], checks_of=checks_of(CheckStatus.PENDING)) == "checking"


def test_only_a_unit_in_review_can_read_checking(clock: FakeClock) -> None:
    planned = stored_unit(UID, state="planned", pr=PR, pushed_at=clock.now())
    review = pushed(clock, ago=3600, uid="add-marker/2")
    pending = checks_of(CheckStatus.PENDING)

    assert effective_state(planned, [planned], checks_of=pending) == PLANNED
    assert effective_state(review, [review], checks_of=pending) == "checking"


def test_recording_a_push_stamps_when(tmp_path: Path, clock: FakeClock) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(UID)])
    store.set_state(UID, IN_REVIEW, pr=PR)

    store.record_push(UID, "abc")

    unit = store.get(UID)
    assert unit.pushed == "abc"
    assert unit.pushed_at == spans.clock.now()
    clock.advance(30)
    store.record_push(UID, "def")
    assert store.get(UID).pushed_at == clock.now()


def test_a_store_written_before_pushed_at_reads_in_review_with_no_checks(
    tmp_path: Path, clock: FakeClock
) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert([stored_unit(UID)])
    store.set_state(UID, IN_REVIEW, pr=PR)
    store.record_push(UID, "abc")
    stored = json.loads(path.read_text())
    for entry in stored["units"]:
        del entry["pushed_at"]
    path.write_text(json.dumps(stored))
    old = store.get(UID)
    assert old.pushed == "abc" and old.pushed_at is None

    assert effective_state(old, [old], checks_of=checks_of()) == IN_REVIEW
    store.record_push(UID, "def")
    fresh = store.get(UID)
    assert effective_state(fresh, [fresh], checks_of=checks_of()) == "checking"


def test_a_replan_keeps_when_the_unit_was_pushed(tmp_path: Path, clock: FakeClock) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(UID)])
    store.set_state(UID, IN_REVIEW, pr=PR)
    store.record_push(UID, "abc")
    stamped = store.get(UID).pushed_at
    clock.advance(5)

    store.upsert([stored_unit(UID)])

    replanned = store.get(UID)
    assert replanned.pushed_at == stamped
    assert effective_state(replanned, [replanned], checks_of=checks_of()) == "checking"


def test_a_status_the_snapshot_does_not_know_reads_as_pending(
    tmp_path: Path, clock: FakeClock
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(UID)])
    store.set_state(UID, IN_REVIEW, pr=PR)
    store.record_push(UID, "abc")
    clock.advance(3600)
    unit = store.get(UID)
    path = state_path(inst.state_dir, unit.repo)

    PrState.save(path, {"7": {"checks": {"CI": "weird"}}})
    assert effective_state(unit, [unit], checks_of=recorded_checks(inst.state_dir)) == "checking"

    PrState.save(path, {"7": "not a dict"})
    assert effective_state(unit, [unit], checks_of=recorded_checks(inst.state_dir)) == IN_REVIEW


def test_checking_has_its_own_name_colour_and_label() -> None:
    style = STATES["checking"]

    assert style.name == "checking"
    assert style.fill != STATES[IN_REVIEW].fill
    label = state_label("checking")
    assert label is not None and label.name == "checking"
    assert "checking" in state_label_names()


def test_the_graph_shows_a_checking_unit_by_its_new_name(clock: FakeClock) -> None:
    unit = pushed(clock, ago=3600)

    page = render_mermaid([unit], checks_of=checks_of(CheckStatus.PENDING))

    assert "· checking" in page
    assert any(line.strip().startswith("classDef checking") for line in page.splitlines())
    assert page.splitlines()[-1].endswith(" checking")
    passed = render_mermaid([unit], checks_of=checks_of(CheckStatus.PASSED))
    assert "· in-review" in passed
    assert "· checking" not in passed


def test_the_state_label_follows_the_derived_status(clock: FakeClock) -> None:
    forge = StandInForge()
    labels = StateLabels(lookup(forge), log=lambda message: None)
    unit = pushed(clock, ago=3600)

    labels.follow(unit, [unit], opened=False, checks_of=checks_of(CheckStatus.PENDING))
    assert forge.on_pr[PR] & state_label_names() == {"checking"}

    labels.follow(unit, [unit], opened=False, checks_of=checks_of(CheckStatus.PASSED))
    assert forge.on_pr[PR] & state_label_names() == {STATES[IN_REVIEW].name}


def test_a_checking_unit_holds_a_queue_place_and_releases_its_dependents(
    clock: FakeClock,
) -> None:
    parent = pushed(clock, ago=3600)
    child = stored_unit("add-marker/2", depends_on=(UID,), groups=(2,))
    graph = [parent, child]
    pending = checks_of(CheckStatus.PENDING)

    assert effective_state(parent, graph, checks_of=pending) == "checking"
    assert effective_state(child, graph, checks_of=pending) == PLANNED, "released, not blocked"
    assert in_progress(parent)
    assert [u.id for u in ready_units(graph, max_concurrent=2, depth_cap=3)] == [child.id]
