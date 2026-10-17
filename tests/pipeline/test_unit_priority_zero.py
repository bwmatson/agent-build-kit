"""A unit may have priority 0, and a zero counts as a priority, never as none.

`unit_priority` is read through the planner (`abk replan`), which raises every
group's priority onto the unit it builds.
"""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.planner import unit_priority
from tests.cli.replan_driver import Replan, answer, planned
from tests.factories import stored_unit, unit
from tests.task_priority_files import tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_unit_takes_priorities_zero_to_five_and_refuses_the_rest() -> None:
    assert unit("feature/1", priority=0).priority == 0
    for value in (6, -1):
        with pytest.raises(ValueError):
            unit("feature/1", priority=value)


def test_a_unit_of_a_zero_group_and_a_normal_group_is_zero(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md("0", None))

    run.run(capsys, "feature", reply=answer(planned("feature/1", (1, 2))))

    assert run.store.get("feature/1").priority == 0


def test_a_unit_of_a_zero_group_alone_is_zero(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md("0"))

    run.run(capsys, "feature", reply=answer(planned("feature/1", (1,))))

    assert run.store.get("feature/1").priority == 0


def test_a_unit_with_no_group_in_the_catalog_is_normal_whatever_it_holds() -> None:
    assert unit_priority(unit("feature/1", priority=0), {}) == 3


def test_a_joined_members_zero_group_counts(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, base=tasks_md("3"), feature=tasks_md("0"))
    run.record("base")
    run.store.upsert([stored_unit("base/1", change="base", groups=(1,))])

    join = {"onto": "base/1", "change": "feature", "groups": [1], "estimated_lines": 80}
    run.run(capsys, "feature", reply=answer(joins=[join]))

    assert [m.change for m in run.store.get("base/1").members()] == ["base", "feature"]
    assert run.store.get("base/1").priority == 0
