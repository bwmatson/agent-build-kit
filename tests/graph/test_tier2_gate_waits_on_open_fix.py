"""A unit about to run a full tier 2 run waits while the fix change of a recorded base
failure is open: parked before the lock and before any test, resumed when the fix is in review
(spec: tier2-waits-on-open-base-failure-fixes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.flakes import add_needs_to_unit
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.factories import stored_unit
from tests.tier2_gate_fakes import GATE_CLEARED, OLD, OTHER_OLD, Planning


def restacked(**kw: Any) -> None:
    return None


def test_a_second_unit_is_parked_gated_on_the_open_fix_before_any_lock_or_test(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix()
    written = planning.changes()

    outcome = planning.tick()

    assert outcome.status == RunStatus.HELD
    stored = planning.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.gated_requeue is RequeueReason.RESUME
    assert planning.needs() == {1: [fix], 2: [fix]}, "a line on each group of the unit"
    assert not planning.ran_tier2, "no test ran"
    assert not planning.installation.tier2_lock.exists(), "the stack lock was never taken"
    assert planning.changes() == written, "the gate writes no change"
    assert fix in stored.note or OLD in stored.note, "a person sees what it waits on"


def test_a_unit_that_has_not_reached_tier_2_has_no_line_until_it_arrives(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    tasks = planning.installation.changes_dir / "add-marker" / "tasks.md"
    before = (planning.store.get("add-marker/1"), tasks.read_text())

    fix = planning.open_fix()

    assert (planning.store.get("add-marker/1"), tasks.read_text()) == before, (
        "nothing scans the other units when a record is appended"
    )
    assert planning.needs() == {}

    assert planning.tick().status == RunStatus.HELD
    assert planning.needs() == {1: [fix], 2: [fix]}


def test_a_unit_run_again_after_a_restack_is_held_by_a_fix_it_does_not_wait_on(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)
    first = planning.open_fix()
    planning.tick()
    second = planning.open_fix(OTHER_OLD, met_by="other/1")

    planning.tick(event=GATE_CLEARED, restack_onto=restacked)
    outcome = planning.tick(restack_onto=restacked)

    assert outcome.status == RunStatus.HELD
    wanted = sorted([first, second])
    assert {group: sorted(fixes) for group, fixes in planning.needs().items()} == {
        1: wanted,
        2: wanted,
    }, "each line is added once; their order in the file is not the point"
    assert not planning.ran_tier2


def test_the_parked_unit_holds_no_place_and_is_listed_as_waiting_on_the_fix_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix()
    planning.tick()

    lines = planning.status(monkeypatch, capsys)

    blocked = [line for line in lines if "blocked: add-marker/1" in line]
    assert len(blocked) == 1, "listed, and so not counted against the unit limit"
    assert f"{fix}/1" in blocked[0]


def test_the_unit_resumes_once_the_fix_is_in_review_and_is_not_parked_again(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix()
    planning.tick()

    def released() -> bool:
        cli.link_needs(planning.installation, store=planning.store)
        cli.release_gated(planning.installation, planning.store)
        return planning.store.get("add-marker/1").gated_requeue is None

    assert not released(), "the fix change's unit has not been reviewed"
    planning.store.set_state(f"{fix}/1", IN_REVIEW, pr=3)
    assert released(), "released once the fix is in review, as for any same-repo wait"

    planning.tick(event=GATE_CLEARED, restack_onto=restacked)
    outcome = planning.tick(restack_onto=restacked)

    assert outcome.status == "open"
    assert planning.ran_tier2, "tier 2 runs: the line on the fix is there"
    assert planning.needs() == {1: [fix], 2: [fix]}
    assert planning.gate.asked, "the gate was asked and let the unit through"


def test_a_unit_of_the_fix_change_itself_runs_tier_2_with_no_new_line(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix()
    planning.store.upsert([stored_unit("add-marker/1", change=fix, groups=(1,))])

    outcome = planning.tick()

    assert planning.gate.asked == ["add-marker/1"]
    assert outcome.status != RunStatus.HELD and planning.ran_tier2
    assert planning.needs(fix) == {}


def test_a_unit_with_a_line_on_the_fix_runs_tier_2_and_gains_no_second_one(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix()
    add_needs_to_unit(
        planning.installation, planning.store.get("add-marker/1"), fix, "failing test"
    )
    before = planning.needs()

    outcome = planning.tick()

    assert planning.gate.asked == ["add-marker/1"]
    assert outcome.status != RunStatus.HELD and planning.ran_tier2
    assert planning.needs() == before == {1: [fix], 2: [fix]}


def test_a_unit_of_another_repo_runs_tier_2_with_no_line(tmp_path: Path) -> None:
    planning = Planning(tmp_path, repo="platform")
    planning.open_fix(repo="app")

    outcome = planning.tick()

    assert planning.gate.asked == ["add-marker/1"]
    assert outcome.status != RunStatus.HELD and planning.ran_tier2
    assert planning.needs() == {}


def test_a_unit_of_one_fix_is_held_by_another_open_fix_and_gains_a_line_on_it_only(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)
    fix_a = planning.open_fix(OLD)
    fix_b = planning.open_fix(OTHER_OLD, met_by="other/1")
    planning.store.upsert([stored_unit("add-marker/1", change=fix_a, groups=(1,))])

    outcome = planning.tick()

    assert outcome.status == RunStatus.HELD
    assert planning.needs(fix_a) == {1: [fix_b]}, "exempt from A, held by B"
    assert not planning.ran_tier2


def test_a_record_whose_fix_change_is_archived_holds_nobody(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix()
    archive = planning.installation.changes_dir / "archive"
    archive.mkdir()
    (planning.installation.changes_dir / fix).rename(archive / f"2026-03-02-{fix}")

    outcome = planning.tick()

    assert planning.gate.asked == ["add-marker/1"]
    assert outcome.status != RunStatus.HELD and planning.ran_tier2
    assert planning.needs() == {}
