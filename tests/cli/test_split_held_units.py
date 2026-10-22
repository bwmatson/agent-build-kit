"""The tick splits a unit held for its size: it is replaced by planned pieces that carry its
dependencies, its pull request is closed and its dependents follow the last piece (spec:
hold-and-split, split-planning)."""

from __future__ import annotations

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import CLOSED, PLANNED
from tests.parked_split_support import stub_round
from tests.split_step_support import DEPENDENT, HELD_ID, PIECES, correct, reply, scene

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_unit_held_for_its_size_is_replaced_by_pieces_with_its_dependencies(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    first, second, third = (run.store.get(uid) for uid in PIECES)
    assert [piece.state for piece in (first, second, third)] == [PLANNED] * 3
    assert first.depends_on == ("base/1",)
    assert second.depends_on == (first.id,)
    assert third.depends_on == (second.id,)
    assert [piece.groups for piece in (first, second, third)] == [(1, 2), (3,), (4, 5)]


def test_the_held_unit_is_closed_as_superseded_and_its_pull_request_is_to_be_closed(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    old = run.store.get(HELD_ID)
    assert (old.state, old.cause) == (CLOSED, Cause.SUPERSEDED)
    assert old.superseded_by == PIECES
    assert old.close_pending is not None and old.close_pending.pr == 17


def test_its_dependents_depend_on_the_last_piece(tmp_path, monkeypatch) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    assert run.store.get(DEPENDENT).depends_on == (PIECES[-1],)


def test_the_tick_says_what_was_done(tmp_path, monkeypatch, capsys) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = reply(*correct())
    capsys.readouterr()

    cli.split_held_units(run.inst, run.store)

    said = capsys.readouterr().out
    assert HELD_ID in said and all(uid in said for uid in PIECES)
    assert "split" in said


def test_a_split_asks_the_planner_once_for_the_held_units_groups(tmp_path, monkeypatch) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    assert run.calls == 1


def test_a_round_runs_the_split_step_after_planning_and_linking(tmp_path, monkeypatch) -> None:
    run = scene(tmp_path, monkeypatch)
    stub_round(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: seen.append("plan"))
    monkeypatch.setattr(cli, "link_needs", lambda inst, **kwargs: seen.append("link"))
    monkeypatch.setattr(cli, "split_held_units", lambda inst, store, **kwargs: seen.append("split"))

    cli.run_round(run.inst, run.store, building=(), only=frozenset(), submit=False)

    assert seen == ["plan", "link", "split"]
