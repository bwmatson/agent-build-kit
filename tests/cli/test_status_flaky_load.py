"""The `flaky:` line of `abk status` adds the load the flake was met under, when it is known
(spec: test-failure-evidence, "Failures can be read with one command")."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake, flake_record
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import stored_unit

TEST = "tests/test_a.py::test_x"


def met(day: int, conditions: dict[str, object]) -> Flake:
    return Flake(
        test=TEST,
        unit="one/1",
        command="uv run pytest -n auto -q",
        output="FAILED",
        at=datetime(2026, 3, day, 9, 30, tzinfo=UTC),
        conditions=conditions,
    )


def flaky_line(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str:
    UnitStore(inst.state_dir / "units.json").upsert([stored_unit("one/1", change="one")])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return next(line for line in capsys.readouterr().out.splitlines() if "flaky:" in line)


def test_the_line_adds_the_load_range_the_flake_was_met_under(
    installation: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    flake_record(installation).append(met(1, {"load_before": 14.0, "load_after": 18.0}))
    flake_record(installation).append(met(2, {"load_before": 12.0, "load_after": 22.0}))

    line = flaky_line(installation, monkeypatch, capsys)

    assert "(load 12 to 22)" in line
    assert TEST in line and "flaked 2 times" in line, "the rest of the line stays"


def test_a_flake_with_no_load_recorded_has_the_line_it_had_beside_one_that_has_it(
    installation: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    flake_record(installation).append(met(1, {"load_before": 14.0, "load_after": 18.0}))
    other = met(2, {}).model_copy(update={"test": "tests/test_b.py::test_y"})
    flake_record(installation).append(other)
    UnitStore(installation.state_dir / "units.json").upsert([stored_unit("one/1", change="one")])
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), installation) == 0

    lines = capsys.readouterr().out.splitlines()
    with_load = next(line for line in lines if TEST in line)
    without = next(line for line in lines if "tests/test_b.py::test_y" in line)
    assert "(load 14 to 18)" in with_load
    assert "load" not in without
