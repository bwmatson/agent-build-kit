"""A settling unit's groups are in the trunk: a replan counts them taken
(spec: merged-waits-for-ci)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import SETTLING
from tests.cli.replan_driver import Replan, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_editing_the_text_of_a_settling_units_group_makes_no_call_and_plans_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    run.store.upsert([unit("feature/1", change="feature", groups=(1,))])
    run.store.set_state("feature/1", SETTLING, pr=3, branch="spec/feature/1")
    run.record("feature")
    run.write("feature", tasks_md(1).replace("Group 1", "Group 1, reworded"))

    results = cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert results["feature"].status == "planned"
    assert [u.id for u in run.store.all()] == ["feature/1"]
    assert run.store.get("feature/1").state == SETTLING
