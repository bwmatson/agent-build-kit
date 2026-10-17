"""A stored priority 0 is kept: the store leaves out only the default, 3.

Each place a zero could be mistaken for "unset" is pinned here through the
store's public calls and through the planner that fills it.
"""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests.cli.replan_driver import Replan, answer, planned
from tests.factories import unit
from tests.task_priority_files import tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT_ID = "add-marker/1"


def records(store: UnitStore) -> dict[str, dict]:
    return {record["id"]: record for record in json.loads(store.path.read_text())["units"]}


def test_a_unit_of_priority_zero_is_written_with_its_key_and_read_back_as_zero(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")

    store.upsert([unit(UNIT_ID, priority=0), unit("add-marker/2", priority=3)])

    written = records(store)
    assert written[UNIT_ID]["priority"] == 0
    assert "priority" not in written["add-marker/2"]
    fresh = UnitStore(store.path)
    assert (fresh.get(UNIT_ID).priority, fresh.get("add-marker/2").priority) == (0, 3)


def test_set_priority_zero_on_an_unstarted_unit_is_stored_and_read_back(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=4)])

    store.set_priority(UNIT_ID, 0)

    assert store.get(UNIT_ID).priority == 0
    assert UnitStore(store.path).get(UNIT_ID).priority == 0
    assert records(store)[UNIT_ID]["priority"] == 0


def test_set_priority_zero_on_a_started_unit_changes_nothing_where_an_unstarted_one_takes_it(
    tmp_path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=4), unit("add-marker/2", priority=4)])
    store.set_state(UNIT_ID, RUNNING, branch="spec/add-marker/1")

    store.set_priority(UNIT_ID, 0)
    store.set_priority("add-marker/2", 0)

    assert store.get(UNIT_ID).priority == 4
    assert store.get("add-marker/2").priority == 0


def test_a_started_unit_of_priority_zero_keeps_it_when_the_plan_says_normal(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=0)])
    store.set_state(UNIT_ID, PLANNED, branch="spec/add-marker/1")

    store.upsert([unit(UNIT_ID)])

    assert store.get(UNIT_ID).priority == 0
    assert records(store)[UNIT_ID]["priority"] == 0


def test_an_unstarted_unit_of_normal_priority_takes_zero_from_the_plan(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])

    store.upsert([unit(UNIT_ID, priority=0)])

    assert store.get(UNIT_ID).priority == 0


def test_planning_over_a_zero_group_stores_zero_for_an_unstarted_unit(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md("3"))
    run.run(capsys, "feature", reply=answer(planned("feature/1", (1,))))
    run.write("feature", tasks_md("0"))

    run.run(capsys, "feature", reply=answer(planned("feature/1", (1,))))

    assert run.store.get("feature/1").priority == 0


def test_replan_of_a_change_whose_default_is_zero_plans_its_units_at_zero(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(None, None, head="Priority: 0\n"))

    code, _ = run.run(
        capsys, "feature", reply=answer(planned("feature/1", (1,)), planned("feature/2", (2,)))
    )

    assert code == 0
    assert [u.priority for u in run.store.all()] == [0, 0]
