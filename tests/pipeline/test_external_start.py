"""The start path leaves a unit whose groups are all held alone (spec: external-work)."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.pipeline.external_file import RELEASED, add_hold, write_holds
from tests.external_support import SINCE, hold, waits_of, world_of
from tests.factories import stored_unit


def reasons(inst, store) -> dict[str, str]:
    return {uid: wait.reason.value for uid, wait in waits_of(inst, store).items()}


def test_a_held_unit_is_parked_external_and_an_ordinary_one_is_admitted_beside_it(
    tmp_path: Path,
) -> None:
    inst, store, folder = world_of(
        tmp_path, stored_unit("feature/1", change="feature"), stored_unit("other/1", change="other")
    )
    add_hold(folder, hold((1,)))

    assert reasons(inst, store) == {"feature/1": "external", "other/1": "ready"}


def test_a_held_unit_takes_no_place_from_the_units_beside_it(tmp_path: Path) -> None:
    inst, store, folder = world_of(
        tmp_path,
        stored_unit("feature/1", change="feature"),
        stored_unit("other/1", change="other"),
        places=1,
    )
    add_hold(folder, hold((1,)))

    assert reasons(inst, store) == {"feature/1": "external", "other/1": "ready"}


def test_a_priority_zero_held_unit_is_still_not_started(tmp_path: Path) -> None:
    inst, store, folder = world_of(tmp_path, stored_unit("feature/1", change="feature", priority=0))
    add_hold(folder, hold((1,)))

    assert reasons(inst, store) == {"feature/1": "external"}


def test_explain_names_the_holder_and_the_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store, folder = world_of(tmp_path, stored_unit("feature/1", change="feature"))
    add_hold(folder, hold((1,)))

    capsys.readouterr()
    assert cmd_explain(argparse.Namespace(unit="feature/1", at=None), inst) == 0
    out = capsys.readouterr().out

    assert "external" in out
    assert "Sam Example" in out
    assert "https://boards.example/items/42" in out


def test_releasing_the_hold_lets_the_next_tick_consider_the_unit(tmp_path: Path) -> None:
    inst, store, folder = world_of(tmp_path, stored_unit("feature/1", change="feature"))
    add_hold(folder, hold((1,)))
    assert reasons(inst, store) == {"feature/1": "external"}

    write_holds(folder, [hold((1,), status=RELEASED)])

    assert reasons(inst, store) == {"feature/1": "ready"}


def test_explain_does_not_report_a_hold_that_had_not_begun_at_the_time_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store, folder = world_of(tmp_path, stored_unit("feature/1", change="feature"))
    add_hold(folder, hold((1,)))
    before = (SINCE - timedelta(days=6)).isoformat()

    capsys.readouterr()
    assert cmd_explain(argparse.Namespace(unit="feature/1", at=before), inst) == 0

    assert "Sam Example" not in capsys.readouterr().out
