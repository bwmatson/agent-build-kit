"""`abk status` lists a failure that is recorded as load (spec: test-failure-evidence, "A load-only
failure"): the failing line of a test whose record says the host was loaded says so, and the line
of one whose record says it was not, or does not say, is as it was."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake, flake_record
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import stored_unit

SLOW = "tests/test_a.py::test_slow"
BROKEN = "tests/test_b.py::test_broken"
UNSAID = "tests/test_c.py::test_unsaid"


def failing(test: str, conditions: dict[str, object]) -> Flake:
    return Flake(
        test=test,
        unit="one/1",
        command="uv run pytest -n auto -q",
        output="FAILED",
        at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
        failing=True,
        conditions=conditions,
    )


def test_status_lists_the_load_failures_with_how_many_and_not_as_flaky(
    installation: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    UnitStore(installation.state_dir / "units.json").upsert([stored_unit("one/1", change="one")])
    record = flake_record(installation)
    for unit in ("one/1", "two/1"):
        record.append(
            failing(SLOW, {"cpus": 4, "load_high": True}).model_copy(
                update={"failing": False, "classification": "load", "unit": unit}
            )
        )
    record.append(
        failing(BROKEN, {"cpus": 4, "load_high": True}).model_copy(
            update={"failing": False, "classification": "load"}
        )
    )
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), installation) == 0

    lines = capsys.readouterr().out.splitlines()
    slow = next(line for line in lines if SLOW in line)
    broken = next(line for line in lines if BROKEN in line)
    # `log` stamps each line with the time, which is not part of what the line says.
    slow, broken = (line.split("] ", 1)[-1] for line in (slow, broken))
    assert slow.strip().startswith("load:") and "2 times" in slow
    assert broken.strip().startswith("load:") and "1 time" in broken and "times" not in broken
    assert not any("flaky:" in line for line in lines), "a load failure is not a flake"


def test_a_loaded_flake_of_a_test_does_not_mark_its_later_unloaded_failure_as_load(
    installation: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    UnitStore(installation.state_dir / "units.json").upsert([stored_unit("one/1", change="one")])
    record = flake_record(installation)
    record.append(
        failing(SLOW, {"cpus": 4, "load_high": True}).model_copy(update={"failing": False})
    )
    record.append(failing(SLOW, {"cpus": 4, "load_high": False}))
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), installation) == 0

    lines = capsys.readouterr().out.splitlines()
    assert "load" not in next(line for line in lines if "failing:" in line and SLOW in line)


def test_a_failing_line_says_when_the_failure_was_recorded_as_load(
    installation: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    UnitStore(installation.state_dir / "units.json").upsert([stored_unit("one/1", change="one")])
    record = flake_record(installation)
    record.append(failing(SLOW, {"cpus": 4, "load_high": True}))
    record.append(failing(BROKEN, {"cpus": 4, "load_high": False}))
    record.append(failing(UNSAID, {}))
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), installation) == 0

    lines = capsys.readouterr().out.splitlines()
    assert "load" in next(line for line in lines if SLOW in line)
    assert "load" not in next(line for line in lines if BROKEN in line)
    assert "load" not in next(line for line in lines if UNSAID in line), "unknown is not loaded"
