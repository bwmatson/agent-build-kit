"""`abk worker resolve <project>`: a project's resolution runs as their own process (spec:
worker-kinds, resolution and verification run as workers).

The worker runs the project's pending resolution runs, each carrying its unit through the whole
build and recording how it ended. The dispatcher admits at most `max_concurrent_resolutions` of
them, and a run owed beyond that is admitted as an ordinary build worker."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli import worker as worker_cli
from agent_build_kit.cli.worker import cmd_worker_resolve
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission import STARTING_TTL
from agent_build_kit.pipeline.file_lock import LockTimeout, file_lock
from agent_build_kit.pipeline.lease import Leases
from agent_build_kit.pipeline.resolution_lane import (
    clear_worker_record,
    lane_held_by_record,
    write_worker_record,
)
from agent_build_kit.pipeline.snapshots import WAKE
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    PLANNED,
    RUNNING,
    project_key,
    project_tag,
)
from tests import fake_clock
from tests.dispatcher_support import (
    FakeSpawner,
    install_spawner,
    lane_workspace,
    parse_worker_command,
)
from tests.emergency_lane_support import build
from tests.factories import git
from tests.lane_run_slots import as_owed_comment
from tests.restack_lane_fakes import moved, repo_behind
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


def test_a_resolve_worker_killed_mid_run_is_started_again_once_its_claim_has_lapsed(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch)
    inst = lane_workspace(tmp_path, stacks=4, resolutions=1)
    project = owe_comment_reworks(builder.store, "c1/1")
    assert tick(inst) == 0
    assert [unit for kind, unit in spawner.calls if kind == "resolve"] == [project]
    # The worker was killed in its run: the record it wrote names a pid that has gone, and the
    # branch's lock file is left with nothing holding it. Its claim on the unit is not cleared.
    unit = builder.store.get("c1/1")
    assert unit.branch is not None
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    write_worker_record(inst.state_dir, project_key(unit), unit, base="main", pid=gone.pid)
    inst.locks_dir.mkdir(parents=True, exist_ok=True)
    stale = inst.locks_dir / f"{re.sub(r'[^A-Za-z0-9]', '_', unit.branch)}.lock"
    stale.write_text(json.dumps({"pid": gone.pid}))
    assert lane_held_by_record(inst.state_dir) == set(), "a record of a dead pid holds nothing"
    clock.advance((STARTING_TTL + timedelta(seconds=1)).total_seconds())

    assert tick(inst) == 0

    assert [unit for kind, unit in spawner.calls if kind == "resolve"] == [project, project]


def test_two_resolve_workers_of_one_project_keep_their_own_records(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    owe_comment_reworks(store, "c1/1", "c2/1")
    first, second = store.get("c1/1"), store.get("c2/1")
    key = project_key(first)
    other = os.getppid()  # a process that is alive

    mine = write_worker_record(tmp_path, key, first, base="main")
    theirs = write_worker_record(tmp_path, key, second, base="main", pid=other)

    assert mine != theirs
    assert lane_held_by_record(tmp_path) == {"c1/1", "c2/1"}
    clear_worker_record(mine)
    assert lane_held_by_record(tmp_path) == {"c2/1"}


def test_a_resolve_worker_leaves_a_unit_another_live_workers_record_names(
    tmp_path: Path, builder: Builder
) -> None:
    inst = workspace(tmp_path)
    project = owe_comment_reworks(builder.store, "c1/1", "c2/1")
    taken = builder.store.get("c1/1")
    # Another resolve worker, alive, is running c1.
    write_worker_record(inst.state_dir, project_key(taken), taken, base="main", pid=os.getppid())

    assert resolve(inst, project) == 0

    assert builder.started == ["c2/1"]


def test_an_in_review_unit_owed_a_restack_is_moved_onto_its_base_and_not_built(
    tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = repo_behind(tmp_path, monkeypatch)
    repo = inst.checkouts["app"]
    builder.store.upsert([stored("feature/3")])
    builder.store.set_state(
        "feature/3", IN_REVIEW, branch="spec/feature/3", pr=9, cause=Cause.BASE_CHANGED
    )
    restacked: list[str] = []

    def restack(**kwargs: Any) -> None:
        restacked.append(kwargs["branch"])
        moved(inst)

    monkeypatch.setattr(worker_cli, "build_stack_moves", lambda *a, **k: {"restack": restack})

    assert resolve(inst, "app") == 0

    assert restacked == ["spec/feature/3"]
    assert git(repo, "rev-parse", "spec/feature/3") == git(repo, "rev-parse", "main")
    assert builder.store.get("feature/3").state == IN_REVIEW
    assert builder.started == [], "a restack is the move only, the unit is not built"


def test_a_unit_whose_attempts_at_its_base_are_spent_is_held_and_not_built(
    tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = repo_behind(tmp_path, monkeypatch)
    builder.store.upsert([stored("feature/3")])
    builder.store.set_state(
        "feature/3", IN_REVIEW, branch="spec/feature/3", pr=9, cause=Cause.BASE_CHANGED
    )
    builder.store.record_conflict_attempt(
        "feature/3",
        tip=git(inst.checkouts["app"], "rev-parse", "main"),
        head="",
        attempts=inst.config.global_limits.max_review_rounds,
        at=datetime.now(UTC),
    )

    assert resolve(inst, "app") == 0

    assert builder.store.get("feature/3").state == HELD
    assert builder.started == []


def test_a_unit_a_person_holds_the_lease_of_is_not_built(tmp_path: Path, builder: Builder) -> None:
    inst = workspace(tmp_path)
    project = owe_comment_reworks(builder.store, "c1/1")
    assert Leases(inst.leases_dir).take("c1/1", "tab:a")

    assert resolve(inst, project) == 0

    assert builder.started == []
