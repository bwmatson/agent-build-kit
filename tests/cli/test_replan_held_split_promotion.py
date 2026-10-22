"""A replan promotes around the holds in force: a unit on a held split lends its urgency to
nothing, as it would not before the planning was done apart (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import Priority
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit
from tests.parked_split_support import hold
from tests.split_workspace import DECLARED, group, tasks_text

pytestmark = pytest.mark.usefixtures("scripted_engine")


def urgent_waiter_on_acp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    """`other/1` is normal; the plan makes `feature/1` (priority 1, split `acp`) wait on it."""
    run = Replan(
        tmp_path,
        monkeypatch,
        tests=dict(e2e_splits=DECLARED),
        feature=tasks_text(group(1, "Split: acp", "Priority: 1")),
        other=tasks_md(1),
    )
    run.store.upsert([stored_unit("other/1", change="other", groups=(1,))])
    run.record("other")
    return run


def waiter() -> str:
    unit = planned("feature/1", (1,), depends_on=("other/1",))
    return answer({**unit, "tier": "e2e-test", "needs_less_urgent": {"other/1": "it is the base"}})


def test_a_waiter_on_a_split_that_is_not_held_promotes_what_it_waits_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = urgent_waiter_on_acp(tmp_path, monkeypatch)

    code, out = run.run(capsys, "feature", reply=waiter())

    assert code == 0, out
    assert run.store.get("other/1").priority == 1


def test_a_waiter_on_a_held_split_promotes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = urgent_waiter_on_acp(tmp_path, monkeypatch)
    hold(run.inst, "acp")

    code, out = run.run(capsys, "feature", reply=waiter())

    assert code == 0, out
    assert run.store.get("feature/1").split == "acp"
    assert run.store.get("other/1").priority == Priority.NORMAL
