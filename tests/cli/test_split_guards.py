"""A split waits while the usage guard refuses planning or a live process holds the unit's branch
lock, uses no round for either, and a unit is split once (spec: hold-and-split, split-planning)."""

from __future__ import annotations

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import CLOSED, HELD
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.split_step_support import HELD_ID, PIECES, correct, reply, scene
from tests.tick_pass import isolate, tick

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_tick_does_not_split_while_the_usage_guard_refuses_planning(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = reply(*correct())
    isolate(monkeypatch)
    run.runtime.supports_usage_tracking = True
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=False, reason="session at 88%")
    )

    tick(run.inst)

    kept = run.store.get(HELD_ID)
    assert (kept.state, kept.held_by, kept.split_rounds_used) == (HELD, HeldBy.SIZE, 0)
    assert run.calls == 0, "a split is a planning call, behind the guard"

    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=True, reason="plenty")
    )
    tick(run.inst)

    assert run.store.get(HELD_ID).state == CLOSED
    assert run.calls == 1


def test_a_branch_held_by_a_live_process_defers_the_split_without_a_round_and_it_is_made_once(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = reply(*correct())
    locks = run.inst.state_dir / "locks"

    with branch_lock(f"spec/{HELD_ID}", root=locks):
        cli.split_held_units(run.inst, run.store)

        kept = run.store.get(HELD_ID)
        assert (kept.state, kept.held_by, kept.split_rounds_used) == (HELD, HeldBy.SIZE, 0)
        assert run.calls == 0

    cli.split_held_units(run.inst, run.store)
    cli.split_held_units(run.inst, run.store)

    assert run.calls == 1
    assert run.store.get(HELD_ID).cause == Cause.SUPERSEDED
    assert run.store.get(HELD_ID).superseded_by == PIECES
    assert [run.store.get(uid).split_rounds_used for uid in PIECES] == [1, 1, 1]
