"""A pre-existing failure is appended to a record in the state directory and listed by
`abk status` (spec: e2e-failures)."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.untouched_failures import PreExistingCount, preexisting_record
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.untouched_failure_fakes import TEST, failing


def test_an_entry_keeps_the_test_unit_command_line_time_and_base_result(
    installation: Installation,
) -> None:
    kept = failing(base_output="line one\n✗ a non-ascii mark\n\nlast line")

    preexisting_record(installation).append(kept)

    (read,) = preexisting_record(installation).entries()
    assert read == kept, "read back by a later reader"
    assert (read.test, read.unit, read.line) == (TEST, "feature/1", "assert 1 == 2")
    assert read.command == "uv run pytest -m local_stack -v"
    assert read.at == datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
    assert read.base_result == "failed"


def test_nothing_recorded_is_an_empty_record(installation: Installation) -> None:
    assert preexisting_record(installation).entries() == []
    assert preexisting_record(installation).counts() == []


def test_the_same_test_met_by_two_units_counts_twice(installation: Installation) -> None:
    record = preexisting_record(installation)
    record.append(failing(unit="feature/1", change="fix-failing-test-one"))
    record.append(failing("tests/far/test_two.py::test_two", unit="feature/1"))
    record.append(failing(unit="other/2"))

    counts = preexisting_record(installation).counts()

    assert sorted(counts, key=lambda c: c.test) == [
        PreExistingCount(test=TEST, count=2, change="fix-failing-test-one"),
        PreExistingCount(test="tests/far/test_two.py::test_two", count=1, change=""),
    ]


def test_the_record_is_not_the_flake_record(installation: Installation) -> None:
    preexisting_record(installation).append(failing())

    assert preexisting_record(installation).path.name == "preexisting-failures.jsonl"
    assert preexisting_record(installation).path.parent == installation.state_dir


def test_status_lists_a_test_once_with_its_count_and_fix_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    UnitStore(tmp_path / "units.json").upsert([stored_unit("one/1", change="one")])
    record = preexisting_record(workspace)
    record.append(failing(unit="one/1", change="fix-failing-test-one"))
    record.append(failing(unit="two/1", change="fix-failing-test-one"))
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    listed = [line for line in lines if TEST in line]
    assert len(listed) == 1, "once, however many units met it"
    assert "pre-existing" in listed[0]
    assert re.search(r"\b2\b", listed[0]), "failed on the base twice"
    assert "fix-failing-test-one" in listed[0]
