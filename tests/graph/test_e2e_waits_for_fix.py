"""A unit whose every e2e-test failure is pre-existing waits for the fix instead of failing,
and the fix is made once for every unit that meets it (spec: e2e-failures)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import wait_on_fix
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting
from tests.e2e_wait_fakes import (
    BROKEN,
    OLD,
    OTHER_OLD,
    OWN,
    Failing,
    Told,
    snapshot_of,
    verdict_of,
)
from tests.factories import stored_unit
from tests.graph_driver import fresh, tick
from tests.pipeline.test_flake_fix_change import (
    change_with_unit,
    changes,
    code_repo,
    flaked,
    waits_on,
)
from tests.untouched_failure_fakes import TEST as RECORDED


def run(tmp_path: Path, *, own=(), broken=(), old=(), told: Told | None = None):
    recorder = fresh(tmp_path)
    e2e = Failing(
        recorder.events,
        snapshot_of(*own, *broken, *old),
        verdict_of(own=own, broken=broken, old=old),
    )
    told = told or Told()
    outcome = tick(
        tmp_path,
        recorder,
        tier="e2e-test",
        run_e2e=e2e.run,
        e2e_verdict=e2e.judged,
        on_preexisting=told,
    )
    return recorder, outcome, told, e2e


def test_a_unit_whose_failures_are_all_pre_existing_is_parked_gated_on_the_fix(
    tmp_path: Path,
) -> None:
    recorder, outcome, told, _ = run(tmp_path, old=(OLD, OTHER_OLD))

    assert told.told == [("add-marker/1", OLD, True), ("add-marker/1", OTHER_OLD, True)]
    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.gated_requeue is RequeueReason.RESUME
    assert OLD in stored.note and OTHER_OLD in stored.note, "a person sees which tests it waits on"
    assert stored.feedback == "", "a failure on the base is not feedback for the agent to fix"
    assert not {"push", "pr"} & set(recorder.events), "nothing is published"


def test_a_unit_of_the_fix_change_is_not_parked_and_fails_as_today(tmp_path: Path) -> None:
    recorder, outcome, told, _ = run(tmp_path, old=(OLD,), told=Told(fix=None))

    assert told.told == [("add-marker/1", OLD, True)]
    assert outcome.status != RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert stored.cause is not Cause.GATED and stored.gated_requeue is None
    assert stored.feedback.startswith("e2e-test failed:")


def test_a_failure_of_its_own_fails_the_unit_and_it_does_not_wait_for_the_pre_existing_one(
    tmp_path: Path,
) -> None:
    recorder, outcome, told, _ = run(tmp_path, own=(OWN,), old=(OLD,))

    assert told.told == [("add-marker/1", OLD, False)], "recorded and fixed, but not waited on"
    assert outcome.status != RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert stored.cause is not Cause.GATED and stored.gated_requeue is None
    assert OWN in stored.feedback


def test_a_failure_broken_by_the_unit_fails_it_and_it_does_not_wait(tmp_path: Path) -> None:
    recorder, outcome, told, _ = run(tmp_path, broken=(BROKEN,), old=(OLD,))

    assert told.told == [("add-marker/1", OLD, False)]
    assert outcome.status != RunStatus.HELD
    assert recorder.store.get("add-marker/1").cause is not Cause.GATED


def test_a_base_run_that_passes_never_parks_a_unit(tmp_path: Path) -> None:
    recorder, outcome, told, e2e = run(tmp_path, broken=(BROKEN,))

    assert e2e.asked == 1, "the node read what the run found of whose each failure is"
    assert told.told == [], "nothing failed on the base, so nothing is recorded or waited on"
    assert outcome.status != RunStatus.HELD
    assert recorder.store.get("add-marker/1").feedback.startswith("e2e-test failed:")


# --- the callable the runner is given ----------------------------------------------


def two_units(installation: Installation) -> tuple[UnitStore, list[StoredUnit]]:
    code_repo(installation)
    first = change_with_unit(installation, "feature", "feature/1")
    second = change_with_unit(installation, "other", "other/1")
    store = UnitStore(installation.root / "units.json")
    store.upsert([first, second])
    return store, [first, second]


def test_two_units_meeting_one_failure_make_one_change_and_two_needs_lines(
    installation: Installation,
) -> None:
    store, (first, second) = two_units(installation)
    on_preexisting = build_on_preexisting(store, installation, log=lambda message: None)
    verdict = verdict_of(old=(RECORDED,))
    (failed,) = verdict.pre_existing

    fixes = [on_preexisting(u, verdict, failed, wait=True) for u in (first, second)]

    assert fixes[0] == fixes[1]
    assert fixes[0] is not None and fixes[0].startswith("fix-failing-")
    assert [c for c in changes(installation) if c.startswith("fix-failing")] == [fixes[0]]
    assert waits_on(installation, "feature") == [fixes[0]]
    assert waits_on(installation, "other") == [fixes[0]]
    assert [(e.unit, e.test, e.change) for e in preexisting_record(installation).entries()] == [
        ("feature/1", RECORDED, fixes[0]),
        ("other/1", RECORDED, fixes[0]),
    ]


def test_a_later_unit_gains_a_line_and_writes_nothing(installation: Installation) -> None:
    store, (first, second) = two_units(installation)
    on_preexisting = build_on_preexisting(store, installation, log=lambda message: None)
    verdict = verdict_of(old=(RECORDED,))
    (failed,) = verdict.pre_existing
    fix = on_preexisting(first, verdict, failed, wait=True)
    assert fix is not None
    before = (installation.changes_dir / fix / "tasks.md").read_text()

    again = on_preexisting(second, verdict, failed, wait=True)

    assert again == fix
    assert (installation.changes_dir / fix / "tasks.md").read_text() == before
    assert waits_on(installation, "other") == [fix]


def test_the_unit_of_the_fix_change_gains_no_line_and_is_told_none(
    installation: Installation,
) -> None:
    store, (first, _) = two_units(installation)
    on_preexisting = build_on_preexisting(store, installation, log=lambda message: None)
    verdict = verdict_of(old=(RECORDED,))
    (failed,) = verdict.pre_existing
    fix = on_preexisting(first, verdict, failed, wait=True)
    assert fix is not None
    own = stored_unit(fix + "/1", change=fix, groups=(1,))
    store.upsert([own])

    answer = on_preexisting(own, verdict, failed, wait=True)

    assert answer is None
    assert waits_on(installation, fix) == []


def test_a_unit_that_does_not_wait_gains_no_line_but_the_failure_is_recorded_and_fixed(
    installation: Installation,
) -> None:
    store, (first, _) = two_units(installation)
    on_preexisting = build_on_preexisting(store, installation, log=lambda message: None)
    verdict = verdict_of(own=(OWN,), old=(RECORDED,))
    (failed,) = verdict.pre_existing

    fix = on_preexisting(first, verdict, failed, wait=False)

    assert fix is not None and (installation.changes_dir / fix).is_dir()
    assert waits_on(installation, "feature") == []
    (entry,) = preexisting_record(installation).entries()
    assert (entry.unit, entry.test, entry.change) == ("feature/1", RECORDED, fix)
    assert entry.command == verdict.command and entry.line == failed.line


def test_the_needs_line_names_the_failing_test_on_the_base(installation: Installation) -> None:
    store, (first, _) = two_units(installation)
    on_preexisting = build_on_preexisting(store, installation, log=lambda message: None)
    verdict = verdict_of(old=(RECORDED,))
    (failed,) = verdict.pre_existing

    fix = on_preexisting(first, verdict, failed, wait=True)

    assert fix is not None
    tasks = (installation.changes_dir / "feature" / "tasks.md").read_text()
    assert f"Needs: {fix} group 1 — failing test {RECORDED} on the base" in tasks


def test_a_flake_fix_for_the_same_test_is_another_change_and_does_not_stand_in(
    installation: Installation,
) -> None:
    store, (first, _) = two_units(installation)
    flake_fix = wait_on_fix(installation, flaked(RECORDED), first)
    on_preexisting = build_on_preexisting(store, installation, log=lambda message: None)
    verdict = verdict_of(old=(RECORDED,))
    (failed,) = verdict.pre_existing

    fix = on_preexisting(first, verdict, failed, wait=True)

    assert fix is not None and flake_fix is not None and fix != flake_fix
    assert set(waits_on(installation, "feature")) == {flake_fix, fix}, "waits on both"
