"""A plan that puts an `[e2e-test]` group in a unit with another group is refused by name and
asked again, whether or not the group is flagged (spec: unit-joining, unit-sizing). Each test
refuses first, so the accepted shape beside it proves the refusal is about the grouping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.planner import GroupTooLarge, PlannerError, parse_graph
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.cli.replan_driver import Replan, answer, planned, tagged_md

pytestmark = pytest.mark.usefixtures("scripted_engine")


def groups(*kinds: str) -> list[TaskGroup]:
    return [
        TaskGroup(number=n, repo="app", tier=kind, title=f"G{n}", line=3 + 6 * n, task_count=2)
        for n, kind in enumerate(kinds, start=1)
    ]


def unit(uid: str, numbers: tuple[int, ...], kind: str, *, depends_on=(), lines: int = 100) -> dict:
    return {
        "id": uid,
        "change": "feature",
        "title": "A unit",
        "repo": "app",
        "tier": kind,
        "depends_on": list(depends_on),
        "estimated_lines": lines,
        "groups": list(numbers),
    }


def plan(kinds: tuple[str, ...], *units: dict) -> None:
    parse_graph(json.dumps({"units": list(units)}), groups=groups(*kinds))


def test_consecutive_e2e_groups_in_one_unit_are_refused_and_one_unit_each_is_accepted() -> None:
    kinds = ("e2e-test",) * 3

    with pytest.raises(PlannerError) as refused:
        plan(kinds, unit("feature/1", (1, 2), "e2e-test"), unit("feature/3", (3,), "e2e-test"))

    message = str(refused.value)
    assert "feature/1" in message
    assert "group 1" in message and "group 2" in message
    assert "[e2e-test]" in message

    plan(
        kinds,
        unit("feature/1", (1,), "e2e-test"),
        unit("feature/2", (2,), "e2e-test", depends_on=("feature/1",)),
        unit("feature/3", (3,), "e2e-test", depends_on=("feature/2",)),
    )


def test_an_e2e_group_with_a_unit_test_group_is_refused() -> None:
    kinds = ("unit-test", "e2e-test")

    with pytest.raises(PlannerError) as refused:
        plan(kinds, unit("feature/1", (1, 2), "e2e-test"))

    message = str(refused.value)
    assert "feature/1" in message and "group 2" in message and "[e2e-test]" in message

    plan(
        kinds,
        unit("feature/1", (1,), "unit-test"),
        unit("feature/2", (2,), "e2e-test", depends_on=("feature/1",)),
    )


def test_a_lone_e2e_group_over_the_ceiling_is_reported_as_needing_its_tasks_split() -> None:
    kinds = ("e2e-test", "e2e-test")

    with pytest.raises(PlannerError) as refused:
        plan(kinds, unit("feature/1", (1, 2), "e2e-test"))
    assert not isinstance(refused.value, GroupTooLarge)

    with pytest.raises(GroupTooLarge, match="split"):
        plan(
            kinds,
            unit("feature/1", (1,), "e2e-test", lines=1500),
            unit("feature/2", (2,), "e2e-test", depends_on=("feature/1",)),
        )


def test_the_refused_plan_is_asked_again_with_the_reason_and_the_next_answer_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("e2e-test", "e2e-test"))
    together = answer(dict(planned("feature/1", (1, 2)), tier="e2e-test"))
    apart = answer(
        dict(planned("feature/1", (1,)), tier="e2e-test"),
        dict(planned("feature/2", (2,), depends_on=("feature/1",)), tier="e2e-test"),
    )

    code, _ = run.run(capsys, "feature", reply=together)

    assert code == 1
    assert run.store.all() == []
    reason = run.records["feature"]["reason"]
    assert "feature/1" in reason

    run.runtime.answer = apart
    cli.plan_all(run.inst, store=run.store)

    assert run.runtime.requests[-1].prompt.rstrip().endswith(reason)
    assert [u.groups for u in run.store.all()] == [(1,), (2,)]
