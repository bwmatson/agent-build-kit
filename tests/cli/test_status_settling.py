"""`abk status` and `abk explain` word a settling unit and a unit on its late fix (spec:
merged-waits-for-ci)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pr_poller import PrState, state_path
from agent_build_kit.pipeline.unit_store import Cause, Pull, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, SETTLING
from tests.conftest import make_installation, run_status
from tests.factories import new_unit

MERGED_AT = datetime(2026, 10, 27, 11, 43, tzinfo=UTC)
FIX_BRANCH = "spec/add-marker/1-fix1"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(tmp_path, planning={"state_dir": "."})


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([new_unit("add-marker/1")])
    return store


def original() -> Pull:
    return Pull(number=4, branch="spec/add-marker/1", merged_at=MERGED_AT, merge_sha="abc123")


def on_late_fix(store: UnitStore) -> None:
    store.set_state("add-marker/1", IN_REVIEW, pr=9, branch=FIX_BRANCH)
    store.set_pulls(
        "add-marker/1",
        (original(), Pull(number=9, branch=FIX_BRANCH, role="late-fix", opened_at=MERGED_AT)),
    )


def test_a_settling_unit_is_shown_waiting_for_its_checks_since_the_merge(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")
    store.set_pulls("add-marker/1", (original(),))

    lines = run_status(inst, monkeypatch, capsys)

    line = next(line for line in lines if "settling: waiting for" in line)
    assert "since" in line


def test_a_unit_on_its_late_fix_shows_both_pull_requests(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    on_late_fix(store)

    lines = run_status(inst, monkeypatch, capsys)

    assert any("late fix #9 after #4" in line for line in lines)


def test_explain_names_the_failure_that_began_the_late_fix(
    inst: Installation, store: UnitStore, capsys: pytest.CaptureFixture[str]
) -> None:
    on_late_fix(store)
    store.set_state(
        "add-marker/1",
        IN_REVIEW,
        pr=9,
        branch=FIX_BRANCH,
        cause=Cause.LATE_FAILURE,
        note="late failure: check unit-suite failed on the base: tests/test_marker.py::test_a",
    )
    capsys.readouterr()

    code = cmd_explain(argparse.Namespace(unit="add-marker/1", at=None), inst)

    out = capsys.readouterr().out
    assert code == 0
    assert "late fix" in out
    assert "unit-suite" in out
    assert "#4" in out


def test_the_settling_line_names_the_checks_still_running_and_not_the_ones_that_passed(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")
    store.set_pulls("add-marker/1", (original(),))
    PrState.save(
        state_path(inst.state_dir, "app"),
        {"4": {"checks": {"test": "pending", "lint": "passed"}}},
    )

    lines = run_status(inst, monkeypatch, capsys)

    line = next(line for line in lines if "settling: waiting for" in line)
    assert "waiting for test" in line
    assert "lint" not in line


def test_a_merged_unit_that_had_a_late_fix_shows_no_late_fix_line_and_explain_says_nothing_of_it(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    on_late_fix(store)
    store.set_state("add-marker/1", MERGED)

    lines = run_status(inst, monkeypatch, capsys)
    code = cmd_explain(argparse.Namespace(unit="add-marker/1", at=None), inst)

    assert not any("late fix" in line for line in lines)
    assert code == 0
    assert "is on its late fix" not in capsys.readouterr().out


def test_a_unit_waiting_to_build_its_late_fix_is_shown_as_one(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")
    store.set_pulls("add-marker/1", (original(),))
    store.set_state(
        "add-marker/1", PLANNED, branch=FIX_BRANCH, cause=Cause.LATE_FAILURE, note="late failure"
    )

    lines = run_status(inst, monkeypatch, capsys)

    assert any("late fix after #4, not opened yet" in line for line in lines)
