"""Only a failure that also fails on the base holds a unit, and an abandoned fix change is left
to the rule for a closed prerequisite (spec: e2e-waits-on-open-base-failure-fixes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.flakes import fix_change_name, flake_record, wait_on_fix
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import CLOSED, PLANNED
from agent_build_kit.pipeline.untouched_failures import PREFIX, preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting
from tests.e2e_base_fakes import Runs, branch, pytest_output, session
from tests.e2e_gate_fakes import OLD, OTHER_OLD, Planning
from tests.e2e_wait_fakes import OWN, Failing, snapshot_of, verdict_of
from tests.factories import stored_unit
from tests.pipeline.test_flake_fix_change import code_repo, flaked


def second_unit(planning: Planning) -> Any:
    """Another unit of the repo, which reaches e2e-test after the record was written."""
    other = stored_unit("second/1", change="second")
    planning.write_change("second")
    planning.store.upsert([other])
    return other


def test_a_units_own_failure_writes_no_record_and_holds_no_unit(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    e2e = Failing(planning.recorder.events, snapshot_of(OWN), verdict_of(own=(OWN,)))
    told = build_on_preexisting(planning.store, planning.installation, log=lambda m: None)
    planning.tick(run_e2e=e2e.run, e2e_verdict=e2e.judged, on_preexisting=told)
    assert preexisting_record(planning.installation).entries() == []

    assert planning.gate(second_unit(planning)) == []
    assert planning.needs("second") == {}


def test_a_flake_writes_no_base_failure_record_and_holds_no_unit(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    code_repo(planning.installation)
    planning.write_change("feature")
    met = stored_unit("feature/1", change="feature")
    planning.store.upsert([met])
    fix = wait_on_fix(planning.installation, flaked(), met)
    flake_record(planning.installation).append(flaked().model_copy(update={"change": fix or ""}))

    outcome = planning.tick()

    assert planning.gate.asked == ["add-marker/1"]
    assert outcome.status != RunStatus.HELD and planning.ran_e2e
    assert planning.needs() == {}


def test_a_run_that_failed_on_an_environment_outage_writes_no_record(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    outage = Failing(planning.recorder.events, snapshot_of(OLD), None)
    told = build_on_preexisting(planning.store, planning.installation, log=lambda m: None)
    planning.tick(run_e2e=outage.run, e2e_verdict=outage.judged, on_preexisting=told)
    assert preexisting_record(planning.installation).entries() == []

    assert planning.gate(second_unit(planning)) == []


def test_with_no_base_runs_nothing_is_recorded_and_no_unit_is_held(tmp_path: Path) -> None:
    planning = Planning(tmp_path / "planning", limits={"e2e_base_runs": 0})
    repo, base = branch(tmp_path, {})
    runs = Runs(repo, pytest_output(failed={OLD: "assert 1 == 2"}), pytest_output(failed={OLD: ""}))
    run = session(tmp_path, runs)

    ok, _ = run.run(cwd=repo, base=base)

    assert not ok and run.verdict is None, "no base run, so nothing is classified"
    assert runs.on_base == []
    assert preexisting_record(planning.installation).entries() == []
    assert planning.gate(second_unit(planning)) == []


def test_a_run_in_flight_when_a_record_is_written_is_classified_and_judged_as_before(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)
    e2e = Failing(planning.recorder.events, snapshot_of(OLD), verdict_of(old=(OLD,)))

    def run(**kw: Any) -> tuple[bool, str]:
        planning.open_fix(OTHER_OLD, met_by="other/1")
        return e2e.run(**kw)

    told = build_on_preexisting(planning.store, planning.installation, log=lambda m: None)
    outcome = planning.tick(run_e2e=run, e2e_verdict=e2e.judged, on_preexisting=told)

    assert planning.gate.asked == ["add-marker/1"], "asked before the run, once"
    assert outcome.status == RunStatus.HELD, "parked by the failure it met, as before"
    assert planning.needs() == {
        1: [fix_change_name(OLD, PREFIX)],
        2: [fix_change_name(OLD, PREFIX)],
    }


def test_a_fix_change_whose_units_were_closed_keeps_the_unit_waiting_and_adds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = Planning(tmp_path)
    fix = planning.open_fix()
    planning.tick()
    planning.store.set_state(f"{fix}/1", CLOSED)
    held = planning.needs()

    for _ in range(2):
        cli.link_needs(planning.installation, store=planning.store)
        cli.release_gated(planning.installation, planning.store)

    stored = planning.store.get("add-marker/1")
    assert (stored.state, stored.cause, stored.gated_requeue) == (
        PLANNED,
        Cause.GATED,
        RequeueReason.RESUME,
    ), "nothing releases it"
    assert any(
        "blocked: add-marker/1" in line and fix in line
        for line in planning.status(monkeypatch, capsys)
    )
    assert planning.needs() == held, "the gate adds no line of its own"
    assert planning.changes() == {"add-marker", "feature", fix}, "and no change"
