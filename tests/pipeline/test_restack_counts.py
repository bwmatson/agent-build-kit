"""A restack changes no count of units: in progress, blocked, queued, or the wait reason
of any unit; and a unit owed a restack is not started in a worker for it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    in_progress,
    ready_units,
)
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.conftest import make_installation, status_lines
from tests.factories import git, init_repo, stored_unit
from tests.restack_lane_fakes import WAIT, Restacks, caused, lane_over

OWED = "feature/3"
NOT_WAITING_FOR_THE_LANE = {WaitReason.SLOT, WaitReason.QUEUE_FULL, WaitReason.BLOCKED}


@pytest.fixture
def moves() -> Restacks:
    return Restacks()


@pytest.fixture
def lane(tmp_path: Path, moves: Restacks) -> Iterator[RestackLane]:
    with lane_over(tmp_path / "locks", moves, owed=lambda graph: {OWED}) as lane:
        yield lane
        moves.release_all()
        lane.drain()


def full_queue() -> list[StoredUnit]:
    """Limit 2: one unit in review and `feature/3` planned for a moved base are in progress;
    `feature/4` is started and blocked, so it is not counted."""
    return [
        stored_unit("feature/1", change="feature", state=IN_REVIEW, pr=1, branch="spec/feature/1"),
        stored_unit("feature/2", change="feature", state=MERGED, pr=2, branch="spec/feature/2"),
        caused(
            OWED,
            PLANNED,
            Cause.BASE_CHANGED,
            branch="spec/feature/3",
            depends_on=("feature/2",),
        ),
        stored_unit(
            "feature/4",
            change="feature",
            state=PLANNED,
            branch="spec/feature/4",
            depends_on=("feature/5",),
        ),
        stored_unit("feature/5", change="feature", state=PLANNED),
    ]


def test_a_unit_being_restacked_still_counts_and_a_blocked_one_is_still_not_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    lane: RestackLane,
    moves: Restacks,
) -> None:
    units = full_queue()
    lane.hand_over(units[2])
    assert moves.begun[OWED].wait(WAIT)

    lines = status_lines(tmp_path, monkeypatch, capsys, units, limit=2)

    assert in_progress(units[2], units)
    full = [line for line in lines if "queue is full" in line]
    assert len(full) == 1
    assert "2 units in progress, limit 2" in full[0]
    assert "1 blocked not counted" in full[0]


def test_a_freshly_unblocked_unit_whose_base_moved_is_restacked_and_then_starts_when_room_opens(
    lane: RestackLane, moves: Restacks
) -> None:
    graph = full_queue()[:3]
    # Its parent went back to planned after the unit last stopped, so the unit waited on it.
    graph[1] = graph[1].model_copy(
        update={
            "history": (
                {"state": "planned", "at": "2026-02-01T00:00:00+00:00"},
                {"state": "merged", "at": "2026-03-01T00:00:00+00:00"},
            )
        }
    )

    def ready(of: list[StoredUnit]) -> list[str]:
        return [
            unit.id
            for unit in ready_units(of, max_concurrent=4, depth_cap=9, max_units_in_progress=1)
        ]

    assert ready(graph) == []
    lane.scan(graph)
    moves.release_all()
    lane.drain()
    assert moves.finished == [OWED]
    assert ready(graph) == []

    graph[0] = graph[0].model_copy(update={"state": MERGED})
    assert ready(graph) == [OWED]


def test_a_unit_queued_for_the_lane_is_not_blocked_and_is_given_no_slot_or_queue_full_reason(
    tmp_path: Path, lane: RestackLane, moves: Restacks
) -> None:
    inst = make_installation(tmp_path, limits={"max_units_in_progress": 9})
    graph = full_queue()
    for unit in graph[:2]:
        lane.hand_over(unit)
    lane.hand_over(graph[2])

    waits = cli.wait_reasons(inst, graph, started=set(), building=set(), only=frozenset())

    assert OWED in lane.waiting
    assert waits[OWED].reason not in NOT_WAITING_FOR_THE_LANE
    assert not waits[OWED].waits_on


# --- a unit owed a restack is not offered to a worker --------------------------------------


@pytest.fixture
def behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    """`spec/feature/3` was cut from `main` before `main` moved: it does not hold its base."""
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    repo = init_repo(inst.checkouts["app"])
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a")
    git(repo, "branch", "spec/feature/3")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "b")
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    return inst


def moved(inst: Installation) -> None:
    git(inst.checkouts["app"], "branch", "-f", "spec/feature/3", "main")


def parked(cause: Cause) -> StoredUnit:
    return caused(OWED, RUNNING, cause, branch="spec/feature/3")


def test_a_unit_owed_a_restack_is_not_offered_to_resumable_units_until_it_is_moved(
    behind: Installation,
) -> None:
    owed = [parked(Cause.BASE_CHANGED)]

    assert cli.resumable_units(behind, owed, only=frozenset()) == []

    moved(behind)
    assert [unit.id for unit in cli.resumable_units(behind, owed, only=frozenset())] == [OWED]


def test_a_unit_recorded_as_a_restack_conflict_is_offered_to_resumable_units_at_once(
    behind: Installation,
) -> None:
    owed = [parked(Cause.BASE_CHANGED)]
    conflicted = [parked(Cause.RESTACK_CONFLICT)]

    assert cli.resumable_units(behind, owed, only=frozenset()) == []
    assert [unit.id for unit in cli.resumable_units(behind, conflicted, only=frozenset())] == [OWED]


def test_a_planned_unit_owed_a_restack_is_not_started_until_it_is_moved(
    behind: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, step in {
        "fetch_all": lambda inst: None,
        "poll_all": lambda inst, **kwargs: None,
        "plan_all": lambda inst, **kwargs: None,
        "has_identity": lambda inst, repo: True,
        "verify_ready": lambda inst, units, **kwargs: lambda change: True,
        "archive_ready_changes": lambda *a, **k: [],
        "current_usage": lambda: None,
        "may_start_unit": lambda r: Decision(may_start=True, reason="plenty"),
    }.items():
        monkeypatch.setattr(cli, name, step)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(OWED, change="feature")])
    store.set_state(OWED, PLANNED, branch="spec/feature/3", cause=Cause.BASE_CHANGED)

    def started() -> list[str]:
        ready = cli.run_round(behind, store, building=(), only=frozenset(), submit=True)
        return [unit.id for unit in ready]

    assert started() == []

    moved(behind)
    assert started() == [OWED]
