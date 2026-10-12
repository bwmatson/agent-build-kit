"""`link_needs` records which dependencies a `Needs:` line asked for, for the graph.

The mark is recomputed from `tasks.md` every tick, so removing a line removes it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.cli.replan_driver import Replan, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def drawn(run: Replan) -> str:
    return render_mermaid(run.store.all())


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    run = Replan(
        tmp_path,
        monkeypatch,
        base=tasks_md(1),
        other=tasks_md(1),
        feature=tasks_md(1, needs={1: "base group 1"}),
    )
    run.store.upsert(
        [
            unit("base/1", change="base", groups=(1,)),
            unit("other/1", change="other", groups=(1,)),
            unit("feature/1", change="feature", groups=(1,), depends_on=("other/1",)),
        ]
    )
    run.store.set_state("base/1", IN_REVIEW, branch="spec/base/1", pr=4)
    run.store.set_state("other/1", IN_REVIEW, branch="spec/other/1", pr=5)
    return run


def test_a_needs_line_is_recorded_beside_the_planners_own_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = setup(tmp_path, monkeypatch)

    cli.link_needs(run.inst, store=run.store)

    feature = run.store.get("feature/1")
    assert set(feature.depends_on) == {"other/1", "base/1"}
    assert feature.needs == ("base/1",)
    assert "base_1 ==>|needs| feature_1" in drawn(run).replace("/", "_")
    assert "other_1 --> feature_1" in drawn(run).replace("/", "_")


def test_removing_the_line_removes_the_mark_at_the_next_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = setup(tmp_path, monkeypatch)
    cli.link_needs(run.inst, store=run.store)
    assert "==>|needs|" in drawn(run)

    run.write("feature", tasks_md(1))
    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("feature/1").needs == ()
    assert "needs" not in drawn(run)
