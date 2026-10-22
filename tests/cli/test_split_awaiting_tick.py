"""A unit held for its size with a split to make is work for a tick, and a unit that cannot be split
is held for a person even while the usage guard refuses planning (spec: hold-and-split)."""

from __future__ import annotations

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import CLOSED, HELD
from agent_build_kit.pipeline.usage_guard import Decision
from tests.split_step_support import HELD_ID, PIECES, correct, reply, scene
from tests.tick_pass import isolate, tick

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_unit_held_for_its_size_is_the_only_work_and_the_tick_splits_it(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch, dependent=False)
    run.record("feature")
    run.runtime.answer = reply(*correct())
    isolate(monkeypatch)

    assert cli.has_work(run.inst, run.store)
    tick(run.inst)

    old = run.store.get(HELD_ID)
    assert (old.state, old.cause, old.superseded_by) == (CLOSED, Cause.SUPERSEDED, PIECES)


def test_a_unit_that_cannot_be_split_is_held_for_a_person_while_the_guard_refuses(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch, used=2)
    run.runtime.answer = reply(*correct())
    run.runtime.supports_usage_tracking = True
    isolate(monkeypatch)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=False, reason="session at 88%")
    )

    tick(run.inst)

    held = run.store.get(HELD_ID)
    assert (held.state, held.held_by) == (HELD, HeldBy.REVIEW)
    assert run.calls == 0
