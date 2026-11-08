"""`abk worker resolve <project>`: a project's resolution runs as their own process (spec:
worker-kinds, resolution and verification run as workers).

The worker runs the project's pending resolution runs, each carrying its unit through the whole
build and recording how it ended. The dispatcher admits at most `max_concurrent_resolutions` of
them, and a run owed beyond that is admitted as an ordinary build worker."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli import worker as worker_cli
from agent_build_kit.cli.worker import cmd_worker_resolve
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import LockTimeout, file_lock
from agent_build_kit.pipeline.snapshots import WAKE
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, project_tag
from tests.dispatcher_support import (
    FakeSpawner,
    install_spawner,
    lane_workspace,
    parse_worker_command,
)
from tests.emergency_lane_support import build
from tests.lane_run_slots import as_owed_comment
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


@pytest.fixture
def spawner(monkeypatch: pytest.MonkeyPatch) -> FakeSpawner:
    return install_spawner(monkeypatch)


def owe_comment_reworks(store: UnitStore, *unit_ids: str) -> str:
    """Store each unit as in review and owed a comment rework; the project they are in."""
    for unit_id in unit_ids:
        unit, _ = build(unit_id, IN_REVIEW)
        store.upsert([unit])
        as_owed_comment(store, unit_id)
    first = store.get(unit_ids[0])
    return project_tag(first.repo, first.project)


def resolve(inst: Installation, project: str) -> int:
    return cmd_worker_resolve(argparse.Namespace(project=project), inst)


def test_the_command_is_abk_worker_resolve() -> None:
    args = parse_worker_command("resolve", "app")

    assert args.project == "app"
    assert args.func is cmd_worker_resolve


def test_a_resolve_worker_carries_each_pending_run_through_the_whole_build_and_records_it(
    tmp_path: Path, builder: Builder
) -> None:
    inst = workspace(tmp_path)
    project = owe_comment_reworks(builder.store, "c1/1", "c2/1")

    code = resolve(inst, project)

    assert code == 0
    assert sorted(builder.started) == ["c1/1", "c2/1"]
    for unit_id in ("c1/1", "c2/1"):
        assert builder.store.get(unit_id).state == IN_REVIEW, "never handed back as planned"
    assert (inst.state_dir / WAKE).exists()


def test_a_resolve_worker_runs_a_run_as_a_moved_base_run_from_the_snapshot(
    tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path)
    project = owe_comment_reworks(builder.store, "c1/1")
    given: dict[str, Any] = {}

    def fake_build(inst: Installation, unit: Any, **kwargs: Any) -> bool:
        given.update(kwargs)
        return True

    monkeypatch.setattr(worker_cli, "build_unit", fake_build)

    assert resolve(inst, project) == 0
    assert given["moved_base_run"] is True
    assert given["from_snapshot"] is True


def test_a_resolve_worker_does_not_hold_the_repo_turn_through_a_whole_run(
    tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path)
    project = owe_comment_reworks(builder.store, "c1/1")
    repo = builder.store.get("c1/1").repo
    turn_free: list[bool] = []

    def fake_build(inst: Installation, unit: Any, **kwargs: Any) -> bool:
        try:
            with file_lock(inst.locks_dir / f"repo-{repo}.lock", 0):
                turn_free.append(True)
        except LockTimeout:
            turn_free.append(False)
        return True

    monkeypatch.setattr(worker_cli, "build_unit", fake_build)

    assert resolve(inst, project) == 0
    assert turn_free == [True], "the repo turn is taken for the phases that write git state only"


def test_a_resolve_worker_with_nothing_owed_builds_nothing_and_wakes(
    tmp_path: Path, builder: Builder
) -> None:
    inst = workspace(tmp_path)
    builder.store.upsert([stored("a/1")])

    assert resolve(inst, "app") == 0
    assert builder.started == []
    assert (inst.state_dir / WAKE).exists()


def test_the_dispatcher_admits_at_most_the_resolution_cap_and_overflows_into_build_workers(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = lane_workspace(tmp_path, stacks=4, resolutions=1)
    project = owe_comment_reworks(builder.store, "c1/1", "c2/1", "c3/1")

    assert tick(inst) == 0

    resolves = [unit for kind, unit in spawner.calls if kind == "resolve"]
    builds = [unit for kind, unit in spawner.calls if kind == "build"]
    assert resolves == [project]
    assert len(builds) == 2
    assert set(builds) <= {"c1/1", "c2/1", "c3/1"}
    assert builder.started == [], "the dispatcher builds nothing itself"
    for unit_id in builds:
        assert builder.store.get(unit_id).starting is not None


def test_an_overflow_run_counts_toward_the_build_workers_and_not_the_resolution_cap(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = lane_workspace(tmp_path, stacks=1, resolutions=1)
    owe_comment_reworks(builder.store, "c1/1", "c2/1", "c3/1")

    assert tick(inst) == 0

    kinds = sorted(kind for kind, _unit in spawner.calls)
    assert kinds == ["build", "resolve"], "one resolve worker, one ordinary slot, the third waits"


def test_an_overflow_run_ranks_after_a_unit_resuming_a_build_and_before_a_never_started_one(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = lane_workspace(tmp_path, stacks=2, resolutions=1)
    # The paused unit has its graph thread parked, which is what makes it resumable.
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: unit_id == "resume/1")
    builder.store.upsert([stored("new/1"), stored("resume/1")])
    builder.store.set_state("resume/1", RUNNING, branch="spec/resume/1")
    builder.store.set_usage_pause("resume/1", datetime.now(UTC) - timedelta(minutes=1))
    owe_comment_reworks(builder.store, "c1/1", "c2/1")

    assert tick(inst) == 0

    builds = [unit for kind, unit in spawner.calls if kind == "build"]
    assert builds[:1] == ["resume/1"], f"the resumed build comes first, got {builds}"
    assert len(builds) == 2, f"one overflow run takes the second slot, got {builds}"
    assert set(builds[1:]) <= {"c1/1", "c2/1"}, f"an overflow run, not a new unit: {builds}"
    assert builder.store.get("new/1").state == PLANNED


def test_a_run_whose_worker_was_killed_is_retried_once_its_marker_has_lapsed(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = lane_workspace(tmp_path, stacks=4, resolutions=1)
    project = owe_comment_reworks(builder.store, "c1/1")
    assert tick(inst) == 0
    assert [unit for kind, unit in spawner.calls if kind == "resolve"] == [project]
    # The worker died: the branch lock file is stale and nothing holds it.
    branch = builder.store.get("c1/1").branch
    assert branch is not None
    (inst.locks_dir).mkdir(parents=True, exist_ok=True)
    for marked in builder.store.all():
        builder.store.set_starting(marked.id, None)

    assert tick(inst) == 0

    assert [unit for kind, unit in spawner.calls if kind == "resolve"] == [project, project]
