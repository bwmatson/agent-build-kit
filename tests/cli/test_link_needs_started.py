"""A `Needs:` line added to a unit that has started is applied by the same test as any
other: reaching its target adds nothing and changes no state, and a target it must
wait for still gates it (spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, RUNNING, waiting_on
from tests.cli.replan_driver import Replan, needs_md, tasks_md
from tests.factories import unit


def started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *targets: str) -> Replan:
    """`feature` is running on `parent`, which is in review on a merged `root`; `late`
    is planned, and `feature` has a `Needs:` line for each change in `targets`."""
    run = Replan(
        tmp_path,
        monkeypatch,
        root=tasks_md(1),
        parent=tasks_md(1),
        feature=needs_md(*(f"{target} group 1" for target in targets)),
        late=tasks_md(1),
    )
    run.store.upsert(
        [
            unit("root/1", change="root", groups=(1,)),
            unit("parent/1", change="parent", groups=(1,), depends_on=("root/1",)),
            unit("feature/1", change="feature", groups=(1,), depends_on=("parent/1",)),
            unit("late/1", change="late", groups=(1,)),
        ]
    )
    run.store.set_state("root/1", MERGED, branch="spec/root/1", pr=1)
    run.store.set_state("parent/1", IN_REVIEW, branch="spec/parent/1", pr=2)
    run.store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    return run


def test_a_line_added_to_a_started_unit_that_reaches_its_target_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = started(tmp_path, monkeypatch, "root")
    before = run.store.get("feature/1")

    cli.link_needs(run.inst, store=run.store)

    after = run.store.get("feature/1")
    assert after.needs == ("root/1",)
    assert (after.depends_on, after.state, after.branch) == (
        before.depends_on,
        RUNNING,
        "spec/feature/1",
    )


def test_a_target_that_is_a_direct_dependency_still_gates_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = started(tmp_path, monkeypatch, "root", "late")
    run.store.set_state("feature/1", PLANNED)

    cli.link_needs(run.inst, store=run.store)

    feature = run.store.get("feature/1")
    assert feature.depends_on == ("parent/1", "late/1")
    assert set(feature.needs) == {"root/1", "late/1"}
    assert [u.id for u in waiting_on(feature, run.store.all())] == ["late/1"]
