"""A replan keeps what the tick recorded on a declared manual step (spec: manual-steps)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import ManualStep
from tests.factories import unit

CHECKED = datetime(2026, 10, 11, tzinfo=UTC)


def planned(step: ManualStep):
    return unit("feature/1").model_copy(update={"manual_steps": (step,)})


def test_a_declared_step_marked_done_stays_done_when_the_unit_is_replanned(
    tmp_path: Path,
) -> None:
    fresh = ManualStep(slug="flip", text="Flip it", runbook="docs/r.md#flip", line=4)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([planned(fresh)])
    store.set_manual_steps(
        "feature/1",
        (
            fresh.model_copy(
                update=dict(done=True, outcome="met", last_line="ok", checked_at=CHECKED)
            ),
        ),
    )

    store.upsert([planned(fresh)])

    (step,) = store.get("feature/1").manual_steps
    assert (step.done, step.outcome, step.last_line, step.checked_at) == (
        True,
        "met",
        "ok",
        CHECKED,
    )
