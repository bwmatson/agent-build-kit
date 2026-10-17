"""A unit whose own e2e-test tests include a held split waits for the split, with nothing
published, and resumes only that split (spec: e2e-split-runs)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import PLANNED
from tests.e2e_park_fakes import (
    FIRST_RUN,
    GATE_CLEARED,
    RAN,
    SECOND_RUN,
    Parking,
    Step,
    holds_of,
)
from tests.e2e_wait_fakes import OLD, Told
from tests.factories import unit
from tests.graph.checkpoint_reads import read_back
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

REASON = "the provider is down"


class Run:
    """A unit at e2e-test over a fake e2e-test answering `steps`, driven tick by tick."""

    def __init__(self, tmp_path: Path, *steps: Step, **held: str) -> None:
        self.tmp_path = tmp_path
        self.recorder: Recorder = fresh(tmp_path)
        self.recorder.store.upsert([unit(tier="e2e-test")])
        self.recorder.made = 1
        self.parking = Parking(self.recorder.events, *steps)
        self.told = Told()
        self.bodies: list[str] = []
        self.held = held or {"acp": REASON}

    def open_pr(self, unit: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        self.bodies.append(body)
        return self.recorder.open_pr(unit, body=body, base=base, cwd=cwd, **bodies)

    def tick(self, **more: Any) -> RunOutcome:
        wired: dict[str, Any] = dict(
            tier="e2e-test",
            run_e2e=self.parking.run,
            e2e_result=self.parking.result,
            e2e_holds=lambda: holds_of(**self.held),
            on_preexisting=self.told,
            open_pr=self.open_pr,
        )
        return tick(self.tmp_path, self.recorder, **{**wired, **more})

    def resume(self, **more: Any) -> RunOutcome:
        """The hold lifts: the parked unit is released, then runs."""
        assert self.stored.cause is Cause.SPLIT_HELD, "a unit waiting on its split is what resumes"
        self.tick(event=GATE_CLEARED, **more)
        return self.tick(**more)

    @property
    def stored(self) -> StoredUnit:
        return self.recorder.store.get("add-marker/1")


def test_a_unit_whose_run_parked_acp_is_held_planned_with_the_split_and_the_reason(
    tmp_path: Path,
) -> None:
    run = Run(tmp_path, Step(parked=("acp",)))

    outcome = run.tick()

    assert outcome.status == RunStatus.HELD
    assert (run.stored.state, run.stored.cause) == (PLANNED, Cause.SPLIT_HELD)
    assert "acp" in run.stored.note and REASON in run.stored.note
    assert run.stored.parked_splits == ["acp"]
    assert run.stored.parked_sha == RAN, "the commit the passing run was on"


def test_a_parked_unit_publishes_nothing_and_has_no_feedback_failure_or_fix(
    tmp_path: Path,
) -> None:
    run = Run(tmp_path, Step(parked=("acp",)))

    run.tick()

    assert run.stored.cause is Cause.SPLIT_HELD, "it parked, rather than doing none of this"
    assert run.stored.feedback == ""
    assert run.told.told == [], "no failure is recorded, so no fix change is written"
    state = read_back(unit_graphs_path(tmp_path / "state"), "add-marker/1").values
    assert state.get("fix_rounds", 0) == 0
    assert not {"push", "pr", "status", "claude:rework", "claude:fix_checks"} & set(
        run.recorder.events
    )


def test_a_unit_with_no_own_test_in_the_held_split_is_not_held(tmp_path: Path) -> None:
    run = Run(tmp_path, Step(parked=()))

    outcome = run.tick()

    assert run.parking.results_read == 1, "the node reads what the run parked, and finds nothing"
    assert outcome.status == "open"
    assert run.stored.cause is not Cause.SPLIT_HELD and run.stored.parked_splits == []
    assert "status" in run.recorder.events


def test_a_unit_whose_other_splits_failed_fails_as_before_and_is_not_parked(
    tmp_path: Path,
) -> None:
    run = Run(tmp_path, Step(ok=False, parked=("acp",), snapshot="FAILED " + OLD))

    outcome = run.tick()

    assert run.parking.results_read == 1, "the node read what the run parked, and did not park"
    assert outcome.status != RunStatus.HELD
    assert run.stored.feedback.startswith("e2e-test failed:")
    assert run.stored.cause is not Cause.SPLIT_HELD and run.stored.parked_splits == []


def test_a_unit_parked_on_two_splits_names_both(tmp_path: Path) -> None:
    run = Run(
        tmp_path,
        Step(parked=("acp", "claude_code")),
        acp="the provider is down",
        claude_code="logged out",
    )

    run.tick()

    assert "acp" in run.stored.note and "claude_code" in run.stored.note
    assert "the provider is down" in run.stored.note and "logged out" in run.stored.note
    assert run.stored.parked_splits == ["acp", "claude_code"]


# --- the resume -------------------------------------------------------------------------


def test_the_resumed_node_runs_only_the_parked_split_on_the_stored_commit(
    tmp_path: Path,
) -> None:
    run = Run(tmp_path, Step(parked=("acp",)), Step(snapshot=SECOND_RUN))
    run.tick()

    outcome = run.resume()

    assert outcome.status == "open"
    assert run.parking.only == [None, "acp"]


def test_the_resumed_node_posts_the_first_runs_result_with_its_own_and_one_status(
    tmp_path: Path,
) -> None:
    run = Run(tmp_path, Step(parked=("acp",)), Step(snapshot=SECOND_RUN))
    run.tick()

    run.resume()

    (body,) = run.bodies
    assert FIRST_RUN in body and SECOND_RUN in body
    assert run.recorder.events.count("status") == 1


def test_the_resumed_node_posts_no_status_when_the_parked_split_failed(tmp_path: Path) -> None:
    run = Run(tmp_path, Step(parked=("acp",)), Step(ok=False, snapshot="FAILED " + OLD))
    run.tick()

    outcome = run.resume()

    assert outcome.status != "open"
    assert run.parking.only == [None, "acp"]
    assert "status" not in run.recorder.events


def test_the_resumed_node_parks_again_when_the_split_is_still_held(tmp_path: Path) -> None:
    run = Run(tmp_path, Step(parked=("acp",)), Step(parked=("acp",)))
    run.tick()

    outcome = run.resume()

    assert run.parking.only == [None, "acp"]
    assert outcome.status == RunStatus.HELD
    assert (run.stored.state, run.stored.cause) == (PLANNED, Cause.SPLIT_HELD)
    assert run.stored.parked_splits == ["acp"] and run.stored.parked_sha == RAN
    assert not {"push", "pr", "status"} & set(run.recorder.events)


def test_the_resumed_node_runs_the_whole_selection_when_the_head_moved(tmp_path: Path) -> None:
    run = Run(tmp_path, Step(parked=("acp",)), Step(snapshot=SECOND_RUN))
    run.tick()
    assert run.stored.parked_sha == RAN, "parked on a commit the head then leaves"

    run.resume(head=lambda cwd: "sha-moved")

    assert run.parking.only == [None, None]


def test_the_stored_parking_is_cleared_when_the_split_passes(tmp_path: Path) -> None:
    run = Run(tmp_path, Step(parked=("acp",)), Step(snapshot=SECOND_RUN))
    run.tick()
    assert run.stored.parked_splits == ["acp"]

    run.resume()

    assert run.stored.parked_splits == [] and run.stored.parked_sha == ""
    assert run.stored.parked_snapshot == ""


def test_a_resume_that_parks_again_keeps_the_runs_of_the_splits_that_passed(
    tmp_path: Path,
) -> None:
    run = Run(
        tmp_path,
        Step(parked=("acp", "claude_code")),
        Step(snapshot=SECOND_RUN),
        Step(parked=("claude_code",), snapshot="STILL-BLOCKED-MARK"),
        acp=REASON,
        claude_code="logged out",
    )
    run.tick()

    run.resume()

    assert run.parking.only == [None, "acp", "claude_code"]
    assert run.stored.parked_splits == ["claude_code"]
    assert FIRST_RUN in run.stored.parked_snapshot and SECOND_RUN in run.stored.parked_snapshot
    assert "STILL-BLOCKED-MARK" not in run.stored.parked_snapshot
