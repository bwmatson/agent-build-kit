"""A unit parked behind a fix for a pre-existing failure is released when the fix merges,
restacked, and runs tier 2 again in full (spec: tier2-failures)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason
from agent_build_kit.pipeline.units import PLANNED
from tests.graph.test_fresh_base_builds import CLEAN, Moving
from tests.graph_driver import fresh, tick
from tests.tier2_wait_fakes import OLD, Failing, Told, snapshot_of, verdict_of

GATE_CLEARED = ResumeEvent(
    kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="gate cleared"
)


def test_a_parked_unit_is_restacked_and_runs_tier_2_again_when_the_fix_merges(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    tier2 = Failing(recorder.events, snapshot_of(OLD), verdict_of(old=(OLD,)))
    overrides: dict[str, Any] = dict(
        tier="tier2", run_e2e=tier2.run, e2e_verdict=tier2.judged, on_preexisting=Told()
    )
    tick(tmp_path, recorder, **overrides)
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED), "parked, to be released"
    parked = len(recorder.events)

    def restack(**kw: Any) -> None:
        recorder.events.append("restack")

    tick(tmp_path, recorder, event=GATE_CLEARED, restack_onto=restack, **overrides)
    outcome = tick(tmp_path, recorder, restack_onto=restack, **overrides)

    after = recorder.events[parked:]
    assert outcome.status == "open"
    assert after.count("tier2") == 1 and tier2.runs == 2, "tier 2 in full, once more"
    assert "tier1" not in after, "a restack that moves nothing runs no tier 1, as before"
    assert after.index("restack") < after.index("tier2") < after.index("push")
    assert "claude:rework" not in after and "claude:fix_checks" not in after


def test_a_released_unit_that_the_restack_moves_runs_tier_1_once_before_tier_2(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tier2 = Failing(recorder.events, snapshot_of(OLD), verdict_of(old=(OLD,)))
    moving = Moving(recorder, None, CLEAN)
    overrides: dict[str, Any] = dict(
        tier="tier2",
        run_e2e=tier2.run,
        e2e_verdict=tier2.judged,
        on_preexisting=Told(),
        restack_onto=moving.restack,
        head=moving.head,
    )
    tick(tmp_path, recorder, **overrides)
    parked = len(recorder.events)

    tick(tmp_path, recorder, event=GATE_CLEARED, **overrides)
    outcome = tick(tmp_path, recorder, **overrides)

    after = recorder.events[parked:]
    assert outcome.status == "open"
    assert after.count("tier1") == 1, "the restack's tier 1 run, neither skipped nor doubled"
    assert after.index("moved") < after.index("tier1") < after.index("push")


def test_the_released_unit_that_fails_tier_2_again_on_the_same_test_is_parked_again(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tier2 = Failing(recorder.events, snapshot_of(OLD), verdict_of(old=(OLD,)), fails=2)
    told = Told()
    overrides: dict[str, Any] = dict(
        tier="tier2", run_e2e=tier2.run, e2e_verdict=tier2.judged, on_preexisting=told
    )
    tick(tmp_path, recorder, **overrides)
    tick(tmp_path, recorder, event=GATE_CLEARED, restack_onto=lambda **kw: None, **overrides)

    outcome = tick(tmp_path, recorder, restack_onto=lambda **kw: None, **overrides)

    assert outcome.status == "held"
    assert [t[1] for t in told.told] == [OLD, OLD], "met again, and waits again"
    assert recorder.store.get("add-marker/1").cause is Cause.GATED
