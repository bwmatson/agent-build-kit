# ruff: noqa: F811 — the imported fixture is requested by name
"""`abk explain` shows the wait of a unit that is gated now, beside an earlier admission record."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.pipeline.admission_record import ADMISSIONS_NAME, read_admissions
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from tests.cli.test_admission_asks_own_account import (  # noqa: F401 — fixtures
    Accounts,
    accounts,
    isolated,
    round_of,
    unit,
)
from tests.pipeline.test_admission_record import installation


def test_a_gated_unit_shows_its_wait_and_the_record_that_admitted_it(
    tmp_path: Path, accounts: Accounts, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, store = installation(tmp_path, [unit("one/1", "app")], limit=3)
    round_of(inst, store)
    assert read_admissions(inst.state_dir / ADMISSIONS_NAME)
    store.set_state("one/1", PLANNED, note="waiting for dep group 1 to merge", cause=Cause.GATED)

    capsys.readouterr()
    assert cmd_explain(argparse.Namespace(unit="one/1", at=None), inst) == 0
    out = capsys.readouterr().out

    assert "waiting for dep group 1 to merge" in out
    assert "admitted" in out
