"""Linking says which unfinished dependents now wait for a merge (spec:
needs-can-wait-for-a-merge): one line for each `Needs: ... merged` line the pair is first
recorded from, nothing edited or requeued, nothing for a unit that has started, a cross-repo
dependent or a parent that has merged, and archived changes are not read. Over the recorded
units, an old `merged` line delays no unit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    waiting_on,
)
from tests.cli.replan_driver import Replan, needs_md
from tests.factories import new_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

RECORDED = Path(__file__).parent.parent / "fixtures" / "stores" / "recorded_units.json"
LINE = "now waits for"


def wait_ids(units: list[StoredUnit]) -> dict[str, set[str]]:
    """What each unfinished unit waits on, asked with no tick record."""
    return {
        u.id: {w.id for w in waiting_on(u, units)}
        for u in units
        if u.state in (PLANNED, FAILED, HELD)
    }


def test_the_line_names_each_unfinished_same_repo_dependent_once_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archived = "## 2. [app] [unit-test] Later\n\nNeeds: base group 1 merged — the fix\n"
    run = Replan(
        tmp_path,
        monkeypatch,
        plan=needs_md("base group 1 merged"),
        fail=needs_md("base group 1 merged"),
        held=needs_md("base group 1 merged"),
        live=needs_md("base group 1 merged"),
        calm=needs_md("ok group 1 merged"),
    )
    (run.inst.changes_dir / "archive" / "old").mkdir(parents=True)
    (run.inst.changes_dir / "archive" / "old" / "tasks.md").write_text(archived)
    run.store.upsert(
        [
            new_unit("base/1", groups=(1,)),
            *(
                new_unit(f"{name}/1", groups=(1,), depends_on=("base/1",))
                for name in ("plan", "fail", "held", "live")
            ),
            new_unit("ok/1", groups=(1,)),
            new_unit("calm/1", groups=(1,), depends_on=("ok/1",)),
        ]
    )
    run.store.set_state("base/1", IN_REVIEW, pr=1)
    run.store.set_state("fail/1", FAILED, branch="spec/fail/1", cause=Cause.FAILED)
    run.store.set_state("held/1", HELD, branch="spec/held/1")
    run.store.set_state("live/1", RUNNING, branch="spec/live/1")
    run.store.set_state("ok/1", MERGED, pr=2)
    named = ("plan/1", "fail/1", "held/1")
    before = {u.id: (u.state, u.cause) for u in run.store.all() if u.id in named}
    capsys.readouterr()

    cli.link_needs(run.inst, store=run.store)

    out = capsys.readouterr().out
    for name in ("plan", "fail", "held"):
        line = f"{name}/1: now waits for base/1 to merge (Needs: ... merged in tasks.md)"
        assert out.count(line) == 1
    assert "live/1: now waits" not in out, "a running unit is not stopped or told"
    assert "calm/1: now waits" not in out, "its parent has merged"
    assert "old/" not in out, "archived changes are not read"
    after = {u.id: (u.state, u.cause) for u in run.store.all() if u.id in named}
    assert before == after, "the units the line names are neither changed nor requeued"

    cli.link_needs(run.inst, store=run.store)

    assert LINE not in capsys.readouterr().out, "the pair is recorded, so the next tick is quiet"


def test_a_cross_repo_dependent_is_told_nothing_because_it_always_waited_for_the_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, use=needs_md("lib group 1"))
    run.store.upsert(
        [
            new_unit("lib/1", groups=(1,), repo="platform"),
            new_unit("use/1", groups=(1,), repo="app", depends_on=("lib/1",)),
        ]
    )
    run.store.set_state("lib/1", IN_REVIEW, pr=1)
    capsys.readouterr()

    cli.link_needs(run.inst, store=run.store)

    assert run.store.get("use/1").merge_needs == ("lib/1",)
    assert LINE not in capsys.readouterr().out


def test_old_merged_lines_over_the_recorded_units_delay_no_unfinished_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    recorded = [StoredUnit.model_validate(u) for u in json.loads(RECORDED.read_text())["units"]]
    run.store.import_units(recorded)
    before = wait_ids(run.store.all())
    merged = {u.id for u in recorded if u.state == MERGED}
    for unit in recorded:
        if unit.state in (PLANNED, FAILED, HELD):
            parents = tuple(dep for dep in unit.depends_on if dep in merged)
            run.store.set_needs(unit.id, parents)
            run.store.set_merge_needs(unit.id, parents)
    assert any(u.merge_needs for u in run.store.all()), "the recorded units have merged parents"
    capsys.readouterr()

    cli.link_needs(run.inst, store=run.store)

    assert wait_ids(run.store.all()) == before
    assert LINE not in capsys.readouterr().out
