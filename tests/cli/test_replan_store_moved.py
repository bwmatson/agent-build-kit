"""A replan writes only what it changed, and stores nothing for a change whose units moved
while the planner was asked (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.runtimes import AgentRequest
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

TWO_UNITS = answer(planned("feature/1", (1,)), planned("feature/2", (2,)))


def started_by_a_tick(run: Replan, unit_id: str) -> None:
    """While the planner is asked, a tick starts `unit_id`."""

    def act(request: AgentRequest) -> None:
        run.store.set_state(unit_id, RUNNING, branch=f"spec/{unit_id}")

    run.runtime.act = act


def test_a_unit_of_another_change_started_meanwhile_stays_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2), other=tasks_md(1))
    run.store.upsert([stored_unit("other/1", change="other", groups=(1,))])
    run.record("other")
    started_by_a_tick(run, "other/1")

    code, _ = run.run(capsys, "feature", reply=TWO_UNITS)

    assert code == 0
    assert run.store.get("other/1").state == RUNNING
    stored = {unit.id for unit in run.store.all() if unit.change == "feature"}
    assert stored == {"feature/1", "feature/2"}
    assert "other" in run.records


def test_a_unit_of_the_change_started_meanwhile_stops_the_plan_from_being_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1, 2))])
    run.record("feature")
    started_by_a_tick(run, "feature/1")

    code, out = run.run(capsys, "feature", reply=TWO_UNITS)

    assert code == 1
    assert "store changed while it was planned" in out
    assert "abk replan feature" in out
    assert run.store.get("feature/1").state == RUNNING
    assert run.store.get("feature/1").groups == (1, 2)
    assert {unit.id for unit in run.store.all()} == {"feature/1"}
