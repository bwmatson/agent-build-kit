"""A pass fills each project's workers and resumes within them (spec: unit-scheduling).

Two projects of one repo each have their own build workers, so a pass runs both
projects' builds at once, starts a project's next unit when one of that project's
builds ends and no other's, and resumes a unit within its own project's free workers.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.tick_driver import count_refreshes
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, workspace

# The longest a build waits for what the pass should make happen meanwhile; only an
# upper bound for a pass that does not.
WAIT = 5

# Refreshes a test lets pass to show a unit is not started.
SEVERAL_REFRESHES = 5

WORKERS = 4

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def two_projects(builder: Builder, per_project: int) -> None:
    builder.store.upsert(
        [
            stored(f"{project}{n}/1", project=project)
            for project in ("web", "api")
            for n in range(1, per_project + 1)
        ]
    )


def test_a_pass_starts_four_units_of_each_project_with_four_workers(
    builder: Builder, tmp_path: Path
) -> None:
    inst = workspace(tmp_path, max_concurrent=WORKERS)
    two_projects(builder, WORKERS)
    everyone = threading.Event()
    lock = threading.Lock()
    active: list[str] = []
    peak: list[list[str]] = []
    most: list[int] = [0]

    def hold(uid: str):
        def script() -> None:
            with lock:
                active.append(uid)
                most[0] = max(most[0], len(active))
                if len(active) == 2 * WORKERS:
                    peak.append(list(active))
                    everyone.set()
            everyone.wait(WAIT)
            with lock:
                active.remove(uid)

        return script

    for unit in builder.store.all():
        builder.scripts[unit.id] = hold(unit.id)

    assert tick(inst) == 0

    assert peak, f"only {most[0]} of {2 * WORKERS} units were building at once"
    assert sum(uid.startswith("web") for uid in peak[0]) == WORKERS


def test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path, max_concurrent=WORKERS)
    two_projects(builder, WORKERS + 1)
    refreshes = count_refreshes(monkeypatch)
    everyone = threading.Event()
    next_started = threading.Event()
    released = threading.Event()
    lock = threading.Lock()
    active: list[str] = []
    at_release: list[str] = []

    def arrive(uid: str) -> None:
        with lock:
            active.append(uid)
            if len(active) == 2 * WORKERS:
                everyone.set()

    def web1() -> None:
        arrive("web1/1")
        everyone.wait(WAIT)  # ends web's first build once eight are building
        with lock:
            active.remove("web1/1")

    def others(uid: str):
        def script() -> None:
            if uid == "web5/1":
                next_started.set()
            arrive(uid)
            released.wait(WAIT)
            with lock:
                active.remove(uid)

        return script

    def releaser() -> None:
        if next_started.wait(WAIT):
            refreshes.wait_for(refreshes.count + SEVERAL_REFRESHES, timeout=WAIT)
        at_release.extend(builder.started)
        released.set()

    for unit in builder.store.all():
        builder.scripts[unit.id] = web1 if unit.id == "web1/1" else others(unit.id)
    watcher = threading.Thread(target=releaser)
    watcher.start()
    try:
        assert tick(inst) == 0
    finally:
        released.set()
        watcher.join()

    assert "web5/1" in at_release, "the freed worker of web was not refilled by web's next unit"
    assert "api5/1" not in at_release, "a build of web ending started a unit of api"


def test_a_unit_is_resumed_within_its_own_projects_free_workers(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """web has a worker free, api's one is taken by a build in flight: the unit left
    partway in web resumes, the one in api waits."""
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert(
        [
            stored("web-left/1", project="web"),
            stored("api-left/1", project="api"),
            stored("api-busy/1", project="api"),
        ]
    )
    for uid in ("web-left/1", "api-left/1", "api-busy/1"):
        builder.store.set_state(uid, RUNNING, branch=f"spec/{uid}")
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    monkeypatch.setattr(cli, "owed_units", lambda inst, units: set())

    ready = cli.run_round(
        inst, builder.store, building={"api-busy/1"}, only=frozenset(), submit=True
    )

    assert [unit.id for unit in ready] == ["web-left/1"]


def test_a_projects_owed_restacks_add_to_its_cap_and_take_none_of_its_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_concurrent_stacks": 1, "max_units_in_progress": 50},
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            new_unit("owed/1", project="web"),
            new_unit("web/1", project="web"),
            new_unit("web/2", project="web"),
            new_unit("api/1", project="api"),
            new_unit("api/2", project="api"),
        ]
    )
    monkeypatch.setattr(cli, "owed_units", lambda inst, units: {"owed/1"})

    ready = cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    assert sorted(unit.id for unit in ready) == ["api/1", "web/1"]
