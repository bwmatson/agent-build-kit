"""What `abk replan` says of a started unit the plan omits, and of a plan refused because it
takes a started unit's group (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import PLANNED
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def with_branch(run: Replan, unit_id: str, *groups: int) -> None:
    run.store.upsert([stored_unit(unit_id, change="feature", groups=groups)])
    run.store.set_state(unit_id, PLANNED, branch=f"spec/{unit_id}")


def test_a_kept_planned_unit_is_named_with_the_way_to_retire_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`feature/3` carries a group `tasks.md` no longer has, so the plan leaves it out; the
    unit in the plan has work too and is not named."""
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    with_branch(run, "feature/3", 9)
    with_branch(run, "feature/4", 1, 2)

    code, out = run.run(capsys, "feature", reply=answer(planned("feature/4", (1, 2))))

    assert "kept: feature/3 has work; not in the plan" in out
    assert "abk retire feature/3 --reason" in out
    assert "kept: feature/4" not in out
    assert code == 0, "a plan that keeps every started unit is not a failure"
    assert run.store.get("feature/3").state == PLANNED


def test_a_refused_plan_exits_one_and_names_both_units_and_the_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    with_branch(run, "feature/1", 1, 2)

    code, out = run.run(capsys, "feature", reply=answer(planned("feature/2", (1, 2))))

    assert code == 1
    assert "feature/1" in out and "feature/2" in out and "group 1" in out


def test_a_bare_replan_lists_the_refused_change_as_given_up_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    with_branch(run, "feature/1", 1, 2)
    run.run(capsys, "feature", reply=answer(planned("feature/2", (1, 2))))

    _, out = run.run(capsys)

    line = next(line for line in out.splitlines() if line.startswith("feature:"))
    assert "given up" in line
    assert "feature/1" in line and "feature/2" in line
