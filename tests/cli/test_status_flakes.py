"""`abk status` lists each flaky test with its count and the change that fixes it
(spec: flaky-tests)."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.flakes import Flake, flake_record
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import stored_unit


def found(test: str, unit: str, change: str) -> Flake:
    return Flake(
        test=test,
        unit=unit,
        command="uv run pytest -n auto -q",
        output="FAILED",
        at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
        change=change,
    )


def test_status_lists_a_flaky_test_with_its_count_and_fix_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    UnitStore(tmp_path / "units.json").upsert([stored_unit("one/1", change="one")])
    record = flake_record(workspace)
    record.append(found("tests/test_a.py::test_x", "one/1", "fix-flaky-test-x"))
    record.append(found("tests/test_a.py::test_x", "two/1", "fix-flaky-test-x"))
    record.append(found("tests/test_b.py::test_y", "one/1", "fix-flaky-test-y"))
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    flaky = next(line for line in lines if "tests/test_a.py::test_x" in line)
    assert "flaky" in flaky
    assert re.search(r"\b2\b", flaky), "flaked twice"
    assert "fix-flaky-test-x" in flaky
    other = next(line for line in lines if "tests/test_b.py::test_y" in line)
    assert re.search(r"\b1\b", other) and "fix-flaky-test-y" in other
