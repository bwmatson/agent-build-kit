"""The first round of a tick says which unfinished dependents now wait for a merge (spec:
needs-can-wait-for-a-merge): one line each, nothing edited or requeued, nothing for a unit that
has started, none for a unit whose parent has merged, and archived changes are not read."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, MERGED, RUNNING
from tests.factories import new_unit
from tests.tick_pass import isolate, tick, workspace

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    isolate(monkeypatch)
    made = workspace(tmp_path)
    monkeypatch.chdir(made.root)
    return made


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def merge_need(store: UnitStore, dependent: str, parent: str) -> None:
    store.set_needs(dependent, (parent,))
    store.set_merge_needs(dependent, (parent,))


def test_the_line_names_each_unfinished_dependent_on_an_unmerged_parent_once_and_changes_nothing(
    inst: Installation, store: UnitStore, capsys: pytest.CaptureFixture[str]
) -> None:
    archived = inst.root / "openspec" / "changes" / "archive" / "old" / "tasks.md"
    archived.parent.mkdir(parents=True)
    archived.write_text(
        "## 2. [app] [unit-test] Later\n\nNeeds: base group 1 merged — the fix\n\n- [ ] 2.1 Test\n"
    )
    store.upsert(
        [
            new_unit("base/1"),
            *(new_unit(f"{name}/1", depends_on=("base/1",)) for name in ("plan", "fail", "held")),
            new_unit("live/1", depends_on=("base/1",)),
            new_unit("old/2", depends_on=("base/1",)),
            new_unit("ok/1"),
            new_unit("calm/1", depends_on=("ok/1",)),
        ]
    )
    store.set_state("base/1", IN_REVIEW, pr=1)
    store.set_state("fail/1", FAILED, branch="spec/fail/1", cause=Cause.FAILED)
    store.set_state("held/1", HELD, branch="spec/held/1")
    store.set_state("live/1", RUNNING, branch="spec/live/1")
    store.set_state("ok/1", MERGED, pr=2)
    for name in ("plan", "fail", "held", "live"):
        merge_need(store, f"{name}/1", "base/1")
    merge_need(store, "calm/1", "ok/1")
    named = ("plan/1", "fail/1", "held/1")
    before = {unit.id: (unit.state, unit.cause) for unit in store.all() if unit.id in named}
    capsys.readouterr()

    assert tick(inst) == 0

    out = capsys.readouterr().out
    for name in ("plan", "fail", "held"):
        line = f"{name}/1: now waits for base/1 to merge (Needs: ... merged in tasks.md)"
        assert out.count(line) == 1
    assert "live/1: now waits" not in out, "a running unit is not stopped or told"
    assert "calm/1: now waits" not in out, "its parent has merged"
    assert "old/2: now waits" not in out, "archived changes are not read"
    after = {unit.id: (unit.state, unit.cause) for unit in store.all() if unit.id in named}
    assert before == after, "the units the line names are neither changed nor requeued"
