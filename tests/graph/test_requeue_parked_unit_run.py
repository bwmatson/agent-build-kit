"""A parked unit requeued for rework or restart runs the agent again from `prepare`, and does not
go to its e2e step first (spec: a-unit-parked-on-a-split-can-be-requeued)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.graph_driver import tick
from tests.parked_split_support import hold, installation
from tests.runner_fakes import Recorder
from tests.split_changed_support import deliver_to_graph, park_after_tick

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = unit().id
TIER = "e2e-test"
NOTE = "retag the test; it uses a scripted agent"


@pytest.mark.parametrize(("mode", "agent_step"), [("rework", "claude:rework"), ("restart", None)])
def test_a_requeued_parked_unit_runs_the_agent_from_prepare_and_the_e2e_step_does_not_come_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, agent_step: str | None
) -> None:
    inst: Installation = installation(tmp_path, acp=True)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(split="acp")])
    recorder = Recorder(store)
    tick(tmp_path, recorder, tier=TIER)
    park_after_tick(store, UNIT, "acp")
    hold(inst, "acp")
    guidance_seen: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        guidance_seen.append(store.get(UNIT).guidance)
        return recorder.claude(prompt, **kwargs)

    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    monkeypatch.setattr(cli, "resume_thread", deliver_to_graph(tmp_path, recorder, TIER))
    recorder.events.clear()

    said: list[str] = []
    code = cli.requeue(inst, UNIT, mode, say=lambda text, error=False: said.append(text), note=NOTE)
    tick(tmp_path, recorder, run=agent, tier=TIER)

    assert code == 0, said
    assert guidance_seen == [NOTE], "the note is stored for the run to read"
    agent_ran = [e for e in recorder.events if e.startswith("claude")]
    assert agent_ran, recorder.events
    if agent_step:
        assert agent_ran[0] == agent_step, "the agent runs again, a rework"
    assert "e2e-test" not in recorder.events[: recorder.events.index(agent_ran[0])]
