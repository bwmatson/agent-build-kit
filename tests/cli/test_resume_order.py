"""Units waiting to resume are resumed in the order new starts are chosen, ahead of new starts, in
every round of a tick (spec: usage-pause-slots, units waiting to resume are resumed in start
order). A unit waiting to resume is `running` with a thread, no lock and no pause."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import FAILED, RUNNING
from tests.cli.usage_pause_support import (
    isolate_round,
    started_by,
    unit,
    with_threads,
    workspace,
)
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
)
from tests.tick_pass import workspace as tick_workspace

pytestmark = pytest.mark.usefixtures("scripted_engine")

WAIT_SECONDS = 20


def test_the_first_unit_in_start_order_is_resumed_and_not_the_first_in_the_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One worker is free: a priority-0 unit waiting to resume goes before a priority-4 one the
    store lists first, and before a priority-0 unit that has never started."""
    isolate_round(tmp_path, monkeypatch)
    inst, store = workspace(
        tmp_path,
        [unit("low/1", priority=4), unit("high/1", priority=0), unit("new/1", priority=0)],
        workers=1,
    )
    for uid in ("low/1", "high/1"):
        store.set_state(uid, RUNNING, branch=f"spec/{uid}")
    with_threads(monkeypatch, "low/1", "high/1")

    assert started_by(inst, store) == ["high/1"]


def test_existing_work_is_resumed_before_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit with a pull request goes before one with only a branch, whatever their priority."""
    isolate_round(tmp_path, monkeypatch)
    inst, store = workspace(
        tmp_path, [unit("branch/1", priority=0), unit("pr/1", priority=3)], workers=1
    )
    store.set_state("branch/1", RUNNING, branch="spec/branch/1")
    store.set_state("pr/1", RUNNING, branch="spec/pr/1", pr=7)
    with_threads(monkeypatch, "branch/1", "pr/1")

    assert started_by(inst, store) == ["pr/1"]


def test_in_a_late_round_of_one_tick_a_free_worker_resumes_the_first_waiting_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two workers, one held by a long build. In the tenth round two units are left waiting to
    resume, the priority-4 one listed first: the free worker resumes the priority-0 one then."""
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)
    builder: Builder = install_builder(tmp_path, monkeypatch)
    inst = tick_workspace(tmp_path, max_concurrent=2)
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.01)
    threads: set[str] = set()
    monkeypatch.setattr(cli, "has_thread", lambda _inst, unit_id: unit_id in threads)
    builder.store.upsert(
        [stored("long/1"), stored("late-low/1", priority=4), stored("late-high/1", priority=0)]
    )
    # Not startable until the tenth round, so the first rounds start the long build alone.
    for uid in ("late-low/1", "late-high/1"):
        builder.store.set_state(uid, FAILED)
    rounds = 0
    real = cli.run_round

    def counting(*args, **kwargs):
        nonlocal rounds
        rounds += 1
        if rounds == 10:
            for uid in ("late-low/1", "late-high/1"):
                builder.store.set_state(uid, RUNNING, branch=f"spec/{uid}")
                threads.add(uid)
        return real(*args, **kwargs)

    monkeypatch.setattr(cli, "run_round", counting)
    resumed = threading.Event()
    release = threading.Event()
    seen: dict[str, list[str]] = {}

    def long_build() -> None:
        resumed.wait(WAIT_SECONDS)
        seen["started"] = list(builder.started)
        release.set()

    def held() -> None:
        release.wait(WAIT_SECONDS)

    builder.scripts["long/1"] = long_build
    builder.scripts["late-high/1"] = held
    builder.scripts["late-low/1"] = held
    builder.before_running["late-high/1"] = resumed.set
    builder.before_running["late-low/1"] = resumed.set

    assert tick(inst) == 0

    assert seen["started"] == ["long/1", "late-high/1"], f"rounds run: {rounds}"
