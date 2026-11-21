"""A failed unit-test run on an unchanged head and base stands in for a new one (spec:
test-run-reuse).

The decision is driven over a ledger file and a fake run that counts its calls, which stands for
the slot-taking suite run: a reused result never calls it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.run_log import TestRun, append_test_run, run_ledger_path
from agent_build_kit.pipeline.unchanged_failure import (
    ReuseContext,
    held_after_reuse,
    merged_since,
    run_or_reuse,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.e2e_base_fakes import branch
from tests.factories import stored_unit
from tests.failure_bundle_fakes import START
from tests.failure_bundle_fakes import run_ledger_rows as _rows
from tests.pipeline.test_flake_isolation import HookedProfile

HEAD = "a" * 40
BASE = "b" * 40
FAILED = ["tests/test_one.py::test_plain", "tests/test_two.py::test_other"]


class Spy:
    """Counts the suite runs, the holds and the log lines of one decision."""

    def __init__(self, *, passes: bool = True, merged: bool = False) -> None:
        self.runs = 0
        self.holds: list[str] = []
        self.lines: list[str] = []
        self.passes = passes
        self.merged = merged
        self.asked: list[datetime] = []

    def run(self) -> tuple[bool, str]:
        self.runs += 1
        return self.passes, "the suite ran"

    def merged_since(self, started: datetime) -> bool:
        self.asked.append(started)
        return self.merged

    def decide(
        self,
        ledger: Path,
        *,
        unit: str = "feature/1",
        head: str = HEAD,
        base: str = BASE,
        rework_note: bool = False,
        feedback: str = "",
    ) -> tuple[bool, str]:
        return run_or_reuse(
            ledger,
            ReuseContext(
                unit=unit, head=head, base=base, rework_note=rework_note, feedback=feedback
            ),
            merged_since=self.merged_since,
            run=self.run,
            hold=self.holds.append,
            log=self.lines.append,
        )


def _row(
    unit: str = "feature/1",
    *,
    outcome: str = "failed",
    head: str | None = HEAD,
    base: str | None = BASE,
    reused: bool = False,
    on_base: bool = False,
    minutes: int = 0,
) -> TestRun:
    return TestRun(
        unit=unit,
        started=(START + timedelta(minutes=minutes)).isoformat(),
        seconds=2760.0,
        outcome=outcome,
        failed=FAILED if outcome == "failed" else [],
        load_start=None,
        load_end=None,
        workers=None,
        tick="t1",
        units_running=[],
        head=head,
        base=base,
        reused=reused,
        on_base=on_base,
    )


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    return run_ledger_path(tmp_path)


def test_a_failure_on_the_same_head_and_base_is_reused_and_takes_no_slot(ledger: Path) -> None:
    append_test_run(ledger, _row())
    spy = Spy()

    passed, output = spy.decide(ledger)

    assert not passed
    assert spy.runs == 0
    assert spy.holds == []
    assert all(test in output for test in FAILED)


def test_a_reused_failure_says_the_run_was_not_repeated(ledger: Path) -> None:
    append_test_run(ledger, _row())
    spy = Spy()

    spy.decide(ledger)

    assert any(
        "unchanged since the failed run at" in line and "not run again" in line
        for line in spy.lines
    )


def test_a_reuse_is_added_to_the_ledger_as_a_reused_row_of_the_same_head_and_base(
    ledger: Path,
) -> None:
    append_test_run(ledger, _row())

    Spy().decide(ledger)

    last = _rows(ledger)[-1]
    assert (last["reused"], last["outcome"], last["head"], last["base"]) == (
        True,
        "failed",
        HEAD,
        BASE,
    )
    assert last["failed"] == FAILED


def test_the_second_reuse_holds_the_unit_naming_the_tests_the_head_and_the_base(
    ledger: Path,
) -> None:
    append_test_run(ledger, _row())
    append_test_run(ledger, _row(reused=True, minutes=5))
    spy = Spy()

    passed, _ = spy.decide(ledger)

    assert not passed
    assert spy.runs == 0
    (note,) = spy.holds
    assert all(text in note for text in [*FAILED, HEAD, BASE])


def test_the_first_reuse_holds_nothing(ledger: Path) -> None:
    append_test_run(ledger, _row())
    spy = Spy()

    spy.decide(ledger)

    assert spy.holds == []


@pytest.mark.parametrize(
    "case",
    [
        "new head",
        "new base",
        "merged since",
        "rework note",
        "passing last run",
        "no head and base",
        "other unit",
        "empty ledger",
    ],
)
def test_a_changed_or_unknown_situation_runs_the_suite(ledger: Path, case: str) -> None:
    rows = {
        "new head": _row(),
        "new base": _row(),
        "merged since": _row(),
        "rework note": _row(),
        "passing last run": _row(outcome="passed"),
        "no head and base": _row(head=None, base=None),
        "other unit": _row("other/1"),
    }
    if case in rows:
        append_test_run(ledger, rows[case])
    spy = Spy(merged=case == "merged since", passes=False)

    result = spy.decide(
        ledger,
        head="c" * 40 if case == "new head" else HEAD,
        base="d" * 40 if case == "new base" else BASE,
        rework_note=case == "rework note",
    )

    assert spy.runs == 1
    assert result == (False, "the suite ran")
    assert spy.holds == []
    assert not any("not run again" in line for line in spy.lines)


def test_a_merged_parent_is_asked_about_from_the_start_of_the_recorded_run(ledger: Path) -> None:
    append_test_run(ledger, _row())
    spy = Spy()

    spy.decide(ledger)

    assert spy.asked == [START]


def test_only_the_last_run_of_the_unit_is_read(ledger: Path) -> None:
    append_test_run(ledger, _row(minutes=0))
    append_test_run(ledger, _row("other/1", minutes=1))
    append_test_run(ledger, _row(outcome="passed", minutes=2))
    spy = Spy()

    spy.decide(ledger)

    assert spy.runs == 1


def test_a_fresh_run_after_a_reuse_starts_the_count_again(ledger: Path) -> None:
    new_head = "c" * 40
    append_test_run(ledger, _row())
    append_test_run(ledger, _row(reused=True, minutes=5))
    append_test_run(ledger, _row(head=new_head, minutes=10))
    spy = Spy()

    spy.decide(ledger, head=new_head)

    assert spy.runs == 0
    assert spy.holds == []


def test_each_unit_is_held_at_its_own_second_reuse(ledger: Path) -> None:
    for unit in ("core/1", "worker/1"):
        append_test_run(ledger, _row(unit, minutes=0))
    spy = Spy()

    for unit in ("core/1", "worker/1"):
        spy.decide(ledger, unit=unit)
    assert (spy.runs, spy.holds) == (0, [])
    for unit in ("core/1", "worker/1"):
        spy.decide(ledger, unit=unit)

    assert spy.runs == 0
    assert len(spy.holds) == 2
    assert all(HEAD in note and BASE in note for note in spy.holds)


def test_a_failure_found_on_the_base_is_run_again_not_reused(ledger: Path) -> None:
    append_test_run(ledger, _row(on_base=True))
    spy = Spy(passes=False)

    result = spy.decide(ledger)

    assert spy.runs == 1
    assert result == (False, "the suite ran")
    assert spy.holds == []


# --- the merged parents, the hold and the unit-test call -----------------------------


def _store(path: Path, merged_at: datetime | None, *, parent_state: str = "merged") -> UnitStore:
    history = [] if merged_at is None else [{"state": "merged", "at": merged_at.isoformat()}]
    store = UnitStore(path / "units.json")
    store.import_units(
        [
            stored_unit("parent/1", change="parent", state=parent_state, history=tuple(history)),
            stored_unit("feature/1", change="feature", depends_on=("parent/1",)),
        ]
    )
    return store


@pytest.mark.parametrize(
    ("merged_at", "parent_state", "expected"),
    [
        (START + timedelta(minutes=1), "merged", True),
        (START - timedelta(minutes=1), "merged", False),
        (None, "merged", True),
        (START + timedelta(minutes=1), "in_review", False),
    ],
    ids=["merged after the run", "merged before it", "merged with no time", "not merged"],
)
def test_a_parent_merged_after_the_run_began_is_a_merge_since(
    tmp_path: Path, merged_at: datetime | None, parent_state: str, expected: bool
) -> None:
    store = _store(tmp_path, merged_at, parent_state=parent_state)

    assert merged_since(store, "feature/1", START) is expected


def test_a_unit_the_store_does_not_know_counts_as_a_merge_since(tmp_path: Path) -> None:
    assert merged_since(_store(tmp_path, None), "unknown/1", START)


@pytest.fixture
def current_unit() -> Iterator[None]:
    token = spans.current_unit.set(("feature/1", "feature", "n1", 1))
    yield
    spans.current_unit.reset(token)


class Silent:
    """A runner that keeps every command it is asked to run and fails the run that starts."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        raise AssertionError(f"the unit-test run started {command}")


def test_the_unit_test_call_reuses_an_unchanged_failure_and_holds_the_unit_at_the_second(
    tmp_path: Path, workspace: Installation, current_unit: None
) -> None:
    repo, base = branch(tmp_path, {})
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    store = UnitStore(workspace.state_dir / "units.json")
    store.upsert([stored_unit("feature/1", change="feature", state="running")])
    ledger = run_ledger_path(workspace.state_dir)
    append_test_run(ledger, _row(head=head, base=base))
    runner, lines = Silent(), []
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, HookedProfile()),
        run=runner,
        changed=lambda *a: ["src/app.py"],
        test_runs=ledger,
        installation=workspace,
        log=lines.append,
    )

    first = unit_test(cwd=repo, base=base)
    second = unit_test(cwd=repo, base=base)

    assert first[0] is False and second[0] is False
    assert runner.commands == [], "a reused failure starts no run and takes no slot"
    assert held_after_reuse(first[1]) is None
    note = held_after_reuse(second[1])
    assert note is not None and head in note and base in note
    assert [row["reused"] for row in _rows(ledger)] == [False, True, True]
    assert store.get("feature/1").state == "running", "the graph holds the unit, not this call"
    assert any("not run again" in line for line in lines)


def test_a_first_reuse_keeps_the_failure_the_fix_agent_was_to_read(ledger: Path) -> None:
    append_test_run(ledger, _row())
    spy = Spy()

    _, output = spy.decide(ledger, feedback="AssertionError: 1 != 2\nline 40 of test_one.py")
    _, again = spy.decide(ledger, feedback=output)

    assert "AssertionError: 1 != 2" in output
    assert again.count("unchanged since the failed run") == 1
