"""A parked unit released because its group's `Split:` changed runs the agent again from
`prepare` as a rework of the stored note, and does not run its e2e step first (spec:
a-parked-unit-follows-its-groups-split)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.graph_driver import tick
from tests.parked_split_support import installation
from tests.runner_fakes import Recorder
from tests.split_changed_support import deliver_to_graph, park_after_tick, write_split

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = unit().id
TIER = "e2e-test"


def test_the_released_unit_reworks_from_the_note_and_the_e2e_step_does_not_come_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst: Installation = installation(tmp_path, acp=True)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(split="acp")])
    recorder = Recorder(store)
    tick(tmp_path, recorder, tier=TIER)
    park_after_tick(store, UNIT, "acp")
    write_split(inst, "claude_code", change="add-marker")
    guidance_seen: list[str] = []
    prompts: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        guidance_seen.append(store.get(UNIT).guidance)
        prompts.append(prompt)
        return recorder.claude(prompt, **kwargs)

    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    monkeypatch.setattr(cli, "resume_thread", deliver_to_graph(tmp_path, recorder, TIER))
    recorder.events.clear()

    cli.release_split_changed(inst, store)
    stored = store.get(UNIT).guidance
    tick(tmp_path, recorder, run=agent, tier=TIER)

    assert "claude_code" in stored, "the note is stored on the unit for the run to read"
    assert guidance_seen == [stored]
    assert recorder.events[0] == "claude:rework", "the agent runs again, a rework"
    assert "claude_code" in prompts[0]
    assert "e2e-test" not in recorder.events[: recorder.events.index("claude:rework")]
