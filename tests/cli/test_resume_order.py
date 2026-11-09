"""Units waiting to resume are resumed in the order new starts are chosen, ahead of new starts, in
every round of a tick (spec: usage-pause-slots, units waiting to resume are resumed in start
order). A unit waiting to resume is `running` with a thread, no lock and no pause."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import RUNNING
from tests.cli.usage_pause_support import (
    isolate_round,
    started_by,
    unit,
    with_threads,
    workspace,
)

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
