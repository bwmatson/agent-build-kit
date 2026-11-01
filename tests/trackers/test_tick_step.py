"""The tick's tracker step: where it runs, how it is isolated, what a state change leaves for it
and what it does for a repo with no tracker (spec: tracker-push)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import telemetry, trackers
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.transport import HostUnavailable, RateLimited
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tracker_file import read_tracker
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.reconciler import ERRORS_COUNTER
from agent_build_kit.trackers.tick_step import is_dirty, sync_trackers
from tests.conftest import make_installation
from tests.factories import init_repo, stored_unit
from tests.forges.stand_in import StandInForge
from tests.trackers.board_support import CHANGE, TASKS, TYPES, board_section, write_change
from tests.trackers.reconciler_support import Call, RecordingTracker
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure

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
    upsert_merged(made, [stored_unit(UNIT, change=CHANGE, repo="app")])
    return made


def upsert_merged(store: UnitStore, units: list[StoredUnit]) -> None:
    """The units in the store, each merged by a pull request of its own (an upsert keeps neither
    a state nor a pull request)."""
    first = 5 + len(store.all())
    store.upsert(units)
    for number, unit in enumerate(units, start=first):
        store.set_state(unit.id, UnitState.MERGED, pr=number, branch=f"spec/{unit.id}")


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


def raw_section(**extra: object) -> dict[str, object]:
    return {
        "kind": "azure_devops",
        "levels": ["change", "group"],
        "azure_devops": {**AZURE_BLOCK, "types": TYPES},
        **extra,
    }


def state_of(tracker: RecordingTracker, marker: str) -> str:
    item = tracker.find_by_marker(marker)
    assert item is not None, marker
    return item.kit_state or item.state


def test_the_step_attaches_the_pull_request_of_a_unit_in_review_or_merged(
    inst: Installation, store: UnitStore
) -> None:
    watching = Watching(board_section(["change", "group"]))
    write_change(inst.changes_dir)

    sync_trackers(inst, store.all())

    group = watching.tracker.find_by_marker(f"{CHANGE}:1")
    assert group is not None
    links = watching.tracker.made("link")
    assert [(call.args[0], call.args[2]) for call in links] == [
        (group.id, "https://stand-in.example/example/app/pull/5")
    ]


def test_a_failing_link_does_not_stop_the_other_units_or_the_next_repo(
    inst: Installation,
    store: UnitStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(app=raw_section(), platform=raw_section())
    watching = Watching(board_section(["change", "group"]))
    configure(app=raw_section(), platform=raw_section())
    write_change(inst.changes_dir)
    write_change(inst.changes_dir, "other", tasks=TASKS.replace("[app]", "[platform]"))
    upsert_merged(
        store,
        [
            stored_unit("other/1", change="other", repo="platform", state=UnitState.MERGED, pr=11),
            stored_unit(
                "other/2",
                change="other",
                repo="platform",
                groups=(2,),
                state=UnitState.MERGED,
                pr=12,
            ),
        ],
    )
    refused = [0]

    def first_link_fails(call: Call) -> Exception | None:
        if call.name == "link" and not refused[0]:
            refused[0] += 1
            return RuntimeError("the link was refused")
        return None

    watching.tracker.fail = first_link_fails
    counted: list[str] = []
    monkeypatch.setattr(telemetry, "count", lambda name, *args, **kwargs: counted.append(name))
    logged: list[str] = []

    sync_trackers(inst, store.all(), log=logged.append)

    # platform is synced first: its first unit fails, its second is still attached, and the
    # app board is pushed afterwards.
    assert len(watching.tracker.made("link")) == 3
    assert watching.tracker.find_by_marker(CHANGE) is not None
    assert ERRORS_COUNTER in counted
    assert any("the link was refused" in line for line in logged)


def test_a_rate_limit_ends_the_attaches_after_one_call_and_one_line(
    inst: Installation, store: UnitStore
) -> None:
    configure(app=raw_section(), platform=raw_section())
    watching = Watching(board_section(["change", "group"]))
    configure(app=raw_section(), platform=raw_section())
    write_change(inst.changes_dir, "other", tasks=TASKS.replace("[app]", "[platform]"))
    upsert_merged(
        store,
        [
            stored_unit("other/1", change="other", repo="platform", state=UnitState.MERGED, pr=11),
            stored_unit(
                "other/2",
                change="other",
                repo="platform",
                groups=(2,),
                state=UnitState.MERGED,
                pr=12,
            ),
        ],
    )
    watching.tracker.fail = lambda call: (
        RateLimited("slow down", retry_after=None) if call.name == "link" else None
    )
    logged: list[str] = []

    sync_trackers(inst, store.all(), log=logged.append)

    assert len(watching.tracker.made("link")) == 1
    assert len([line for line in logged if "rate limited" in line]) == 1


def test_a_repo_whose_pass_failed_attaches_nothing(inst: Installation, store: UnitStore) -> None:
    watching = Watching(board_section(["change", "group"]))
    write_change(inst.changes_dir)
    watching.tracker.fail = lambda call: (
        HostUnavailable("create", "host answered 503", 4) if call.name == "create" else None
    )
    logged: list[str] = []

    sync_trackers(inst, store.all(), log=logged.append)

    assert not watching.tracker.made("link")
    assert len(logged) == 1


def test_the_step_creates_no_more_than_the_configured_number_per_run(
    inst: Installation, store: UnitStore
) -> None:
    watching = Watching(board_section(["change", "group"]))
    configure(app=raw_section(create_cap=2))
    write_change(inst.changes_dir)

    sync_trackers(inst, store.all())
    assert len(watching.tracker.made("create")) == 2

    sync_trackers(inst, store.all())
    assert len(watching.tracker.made("create")) == 3


def test_a_change_archived_in_the_round_it_finishes_ends_done_without_new_items(
    inst: Installation, store: UnitStore
) -> None:
    watching = Watching(board_section(["change", "group"]))
    write_change(inst.changes_dir)
    both = [unit.model_copy(update={"groups": (1, 2)}) for unit in store.all()]
    reviewing = [unit.model_copy(update={"state": UnitState.IN_REVIEW}) for unit in both]
    sync_trackers(inst, reviewing)
    assert state_of(watching.tracker, f"{CHANGE}:1") == "active"
    made = len(watching.tracker.made("create"))
    archive = inst.changes_dir / "archive"
    archive.mkdir()
    (inst.changes_dir / CHANGE).rename(archive / f"2026-10-01-{CHANGE}")

    sync_trackers(inst, both)

    assert state_of(watching.tracker, f"{CHANGE}:1") == "done"
    assert state_of(watching.tracker, CHANGE) == "done"
    assert len(watching.tracker.made("create")) == made
