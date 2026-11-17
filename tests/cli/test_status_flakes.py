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
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import HELD
from tests.conftest import make_installation, status_lines
from tests.factories import RECHECK_BUNDLES, RECHECK_NOTE, RECHECK_TEST, stored_unit


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
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    flaky = next(line for line in lines if "tests/test_a.py::test_x" in line)
    assert "flaky" in flaky
    assert re.search(r"\b2\b", flaky), "flaked twice"
    assert "fix-flaky-test-x" in flaky
    other = next(line for line in lines if "tests/test_b.py::test_y" in line)
    assert re.search(r"\b1\b", other) and "fix-flaky-test-y" in other


def test_status_shows_only_a_unit_held_after_a_recheck_as_held_by_the_checks_with_bundles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def record(store: UnitStore) -> None:
        store.upsert([stored_unit("one/1", change="one"), stored_unit("two/1", change="two")])
        store.set_state(
            "one/1", HELD, note=RECHECK_NOTE, cause=Cause.NEEDS_HUMAN, held_by=HeldBy.CHECKS
        )
        store.set_state(
            "two/1", HELD, note="the reviewer asked for a person", cause=Cause.NEEDS_HUMAN
        )

    lines = status_lines(tmp_path, monkeypatch, capsys, record=record)

    held = [line for line in lines if "held by the checks" in line]
    assert len(held) == 1
    assert "one/1" in held[0]
    assert RECHECK_TEST in held[0]
    assert all(bundle in held[0] for bundle in RECHECK_BUNDLES)
