"""A unit that meets a flake is parked gated, and resumes at tier 1 once the fix has
merged (spec: flaky-tests).

Tier 1 is faked at the point the runner binds it: it raises `FlakeFound` where the real one
finds that every failed test passed both serial reruns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.flakes import Flake, FlakeFound
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import PLANNED, Unit
from tests.graph.test_fresh_base_builds import CLEAN, Moving
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

TEST = "tests/test_widget.py::test_renders_the_label"
FLAKE = Flake(
    test=TEST,
    command="uv run pytest -n auto -q",
    output="FAILED tests/test_widget.py::test_renders_the_label - assert 'a' == 'b'\n",
    at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
)
GATE_CLEARED = ResumeEvent(
    kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="gate cleared"
)


class Flaking:
    """Tier 1 that finds a flake on its `nth` run and answers the recorder's otherwise."""

    def __init__(self, recorder: Recorder, *, nth: int) -> None:
        self.recorder = recorder
        self.nth = nth
        self.runs = 0

    def __call__(self, *, cwd: Path, base: str = "main", whole_repo: bool = False):
        self.runs += 1
        if self.runs == self.nth:
            self.recorder.events.append("tier1")
            raise FlakeFound((FLAKE,))
        return self.recorder.tier1(cwd=cwd, base=base, whole_repo=whole_repo)


class Told:
    """What the runner was told of each flake, and for which unit."""

    def __init__(self) -> None:
        self.flakes: list[tuple[str, str]] = []

    def __call__(self, unit: Unit, flake: Flake) -> None:
        self.flakes.append((unit.id, flake.test))


def test_the_unit_is_told_of_the_flake_and_parked_gated_instead_of_failing(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    told = Told()

    outcome = tick(tmp_path, recorder, run_tier1=Flaking(recorder, nth=1), on_flake=told)

    assert told.flakes == [("add-marker/1", TEST)]
    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert TEST in stored.note, "a person reading the unit sees which test it waits on"
    assert stored.gated_requeue is RequeueReason.RESUME, (
        "the requeue that the gate's release delivers is waiting"
    )
    assert stored.feedback == "", "a flake is not feedback for the agent to fix"
    assert not {"review", "push", "pr"} & set(recorder.events)


def test_the_parked_unit_runs_tier_1_again_restacked_when_the_gate_clears(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    tier1 = Flaking(recorder, nth=1)
    tick(tmp_path, recorder, run_tier1=tier1, on_flake=Told())
    parked = len(recorder.events)

    def restack(**kw: Any) -> None:
        recorder.events.append("restack")

    tick(tmp_path, recorder, event=GATE_CLEARED, run_tier1=tier1, restack_onto=restack)
    outcome = tick(tmp_path, recorder, run_tier1=tier1, restack_onto=restack)

    after = recorder.events[parked:]
    assert outcome.status == "open"
    assert "restack" in after, "moved onto the base the fix has merged to"
    assert after.index("restack") < after.index("tier1") < after.index("push")
    assert "claude:rework" not in after and "claude:fix_checks" not in after


def test_a_flake_on_the_base_does_not_send_the_unit_back_as_a_moved_base(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    moving = Moving(recorder, CLEAN)
    told = Told()

    outcome = tick(
        tmp_path,
        recorder,
        run_tier1=Flaking(recorder, nth=2),
        on_flake=told,
        **moving.overrides(),
    )

    assert recorder.events.count("tier1") == 2, "the second run is the one after the move"
    assert told.flakes == [("add-marker/1", TEST)]
    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert "base moved" not in stored.note
    assert stored.feedback == "", "no tier 1 failure is left for the agent"
    assert "push" not in recorder.events
