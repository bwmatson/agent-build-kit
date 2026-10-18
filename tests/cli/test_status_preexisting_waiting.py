"""Each `pre-existing:` line of `abk status` says how many units wait on its fix change
(spec: e2e-waits-on-open-base-failure-fixes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.untouched_failures import preexisting_record
from tests.conftest import make_installation, status_lines
from tests.factories import stored_unit
from tests.untouched_failure_fakes import failing

ONE = "tests/far/test_one.py::test_one"
TWO = "tests/far/test_two.py::test_two"


def line_of(lines: list[str], test: str) -> str:
    return next(line for line in lines if f"pre-existing: {test}" in line)


def status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    waiting_on_one: int,
    waiting_on_two: int,
) -> list[str]:
    """The status of a repo with two recorded failures, each fixed by an open change that has
    a unit, and the given number of other units waiting on each."""
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    record = preexisting_record(workspace)
    record.append(failing(ONE, "met/1", change="fix-one"))
    record.append(failing(TWO, "met/1", change="fix-two"))
    units = [
        stored_unit("fix-one/1", change="fix-one"),
        stored_unit("fix-two/1", change="fix-two"),
    ]
    for number in range(waiting_on_one):
        waits = stored_unit(f"one{number}/1", change=f"one{number}", depends_on=("fix-one/1",))
        units.append(waits)
    for number in range(waiting_on_two):
        waits = stored_unit(f"two{number}/1", change=f"two{number}", depends_on=("fix-two/1",))
        units.append(waits)
    return status_lines(tmp_path, monkeypatch, capsys, units)


def test_the_line_ends_with_the_number_of_units_waiting_on_its_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status(tmp_path, monkeypatch, capsys, waiting_on_one=3, waiting_on_two=1)

    assert line_of(lines, ONE).endswith("3 units waiting")
    assert line_of(lines, TWO).endswith("1 unit waiting")


def test_a_line_with_no_unit_waiting_is_unchanged_beside_one_that_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status(tmp_path, monkeypatch, capsys, waiting_on_one=2, waiting_on_two=0)

    assert line_of(lines, ONE).endswith("2 units waiting")
    assert line_of(lines, TWO).endswith("failed on the base 1 time, fix fix-two")
