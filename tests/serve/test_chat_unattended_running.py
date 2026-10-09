"""A unit the store has as running while no process holds its branch (its tick died before
resuming it) is not streaming a step: the page shows it read-only and says it is paused."""

from __future__ import annotations

import httpx

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.chat_serving import record_session
from tests.serving import seed_pipeline


def test_a_running_unit_nothing_is_building_is_paused_not_streaming(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    record_session(inst, "feature/7", "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e51", runtime="claude_code")
    UnitStore(inst.state_dir / "units.json").set_state(
        "feature/7", RUNNING, note="requeued", cause=Cause.REQUEUED
    )

    shown = api.get("/api/units/feature/7/agent", params={"tab": "t1"}).json()

    assert shown["state"] == "paused"
    assert shown["composer"]["enabled"] is False
    assert "step is running" not in shown["composer"]["reason"].lower()
    assert "paused" in shown["composer"]["reason"].lower()
