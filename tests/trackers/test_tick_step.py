"""The tick's tracker step: where it runs, how it is isolated, what a state change leaves for it
and what it does for a repo with no tracker (spec: tracker-push)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tracker_file import read_tracker
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.tick_step import is_dirty, sync_trackers
from tests.conftest import make_installation
from tests.factories import init_repo, stored_unit
from tests.forges.stand_in import StandInForge
from tests.trackers.board_support import CHANGE, board_section, write_change
from tests.trackers.reconciler_support import RecordingTracker
from tests.trackers.tracker_section_support import configure

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = f"{CHANGE}/1"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_units_in_progress": 50},
    )


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))
    yield
    trackers.unregister("azure_devops")


@pytest.fixture
def store(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> UnitStore:
    forge = StandInForge()
    monkeypatch.setattr(inst, "forge_of", lambda name: (forge, forge.repo_id()))
    for checkout in inst.checkouts.values():
        init_repo(checkout)
    made = cli.store_for(inst)
    made.upsert([stored_unit(UNIT, change=CHANGE, repo="app", state=UnitState.MERGED, pr=5)])
    return made


class Watching:
    """A tracker registered for the kind that records every call and every time it is built."""

    def __init__(self, section: TrackerSection) -> None:
        self.tracker = RecordingTracker()
        self.built = 0
        trackers.register(section.kind, self._factory)

    def _factory(self, section: TrackerSection) -> RecordingTracker:
        self.built += 1
        return self.tracker

    @property
    def touched(self) -> bool:
        return bool(self.tracker.calls) or bool(self.built)


def run(inst: Installation, store: UnitStore) -> None:
    cli.run_round(inst, store, building=set(), started=set(), only=frozenset(), submit=True)


def test_the_step_runs_after_the_label_sweep(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    monkeypatch.setattr(cli, "_sweep_labels", lambda inst, store: order.append("labels"))
    monkeypatch.setattr(cli, "sync_trackers", lambda *args, **kwargs: order.append("trackers"))

    run(inst, store)

    assert order == ["labels", "trackers"]


def test_a_step_that_raises_does_not_fail_the_round(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the board is on fire")

    monkeypatch.setattr(cli, "sync_trackers", broken)
    later: list[str] = []
    monkeypatch.setattr(cli, "_sweep_outcomes", lambda inst, store: later.append("outcomes"))

    run(inst, store)

    assert "syncing trackers failed" in capsys.readouterr().out
    assert later == ["outcomes"]


def test_a_state_change_marks_the_mirror_dirty_and_makes_no_tracker_call(
    inst: Installation, store: UnitStore
) -> None:
    watching = Watching(board_section(["change", "group"]))
    watching.tracker.fail = lambda call: AssertionError(f"a state change called {call.name}")

    store.set_state(UNIT, UnitState.RUNNING, note="started")

    assert is_dirty(inst.state_dir)
    assert not watching.touched


def test_a_state_change_with_no_tracker_section_marks_nothing(
    inst: Installation, store: UnitStore
) -> None:
    store.set_state(UNIT, UnitState.RUNNING, note="started")

    assert not is_dirty(inst.state_dir)


def test_with_no_tracker_section_the_step_calls_nothing_and_writes_nothing(
    inst: Installation, store: UnitStore
) -> None:
    watching = Watching(board_section(["change", "group"]))
    configure(app=None)
    write_change(inst.changes_dir)
    before = sorted(path for path in inst.state_dir.rglob("*"))

    sync_trackers(inst, store.all())

    assert not watching.touched
    assert read_tracker(inst.changes_dir / CHANGE) is None
    assert sorted(path for path in inst.state_dir.rglob("*")) == before
    assert not list(inst.state_dir.glob("tracker-*.json"))


def test_with_a_tracker_section_the_step_pushes_the_board(
    inst: Installation, store: UnitStore
) -> None:
    watching = Watching(board_section(["change", "group"]))
    write_change(inst.changes_dir)

    sync_trackers(inst, store.all())

    assert watching.tracker.find_by_marker(CHANGE) is not None
    assert watching.tracker.find_by_marker(f"{CHANGE}:1") is not None
