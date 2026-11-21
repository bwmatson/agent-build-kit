"""The second reuse of an unchanged failed unit-test run holds its unit for a person (spec:
test-run-reuse): the graph acts on the result, so the checks run no fix agent, the held unit
carries the note and nothing is saved for a fix agent. The first reuse is a failure like any other.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.run_log import TestRun, append_test_run, run_ledger_path
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unchanged_failure import ReuseContext, run_or_reuse
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import HELD
from tests.factories import unit
from tests.failure_bundle_fakes import START
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh

HEAD = "a" * 40
BASE = "b" * 40
TEST = "tests/test_widget.py::test_renders_the_label"


def reuse_output(directory: Path, *, earlier_reuses: int) -> str:
    """What the unit-test call hands back for a failure recorded `earlier_reuses` reuses ago."""
    ledger = run_ledger_path(directory)
    for reused in [False] + [True] * earlier_reuses:
        append_test_run(
            ledger,
            TestRun(
                unit=unit().id,
                started=START.isoformat(),
                seconds=1.0,
                outcome="failed",
                failed=[TEST],
                load_start=None,
                load_end=None,
                workers=None,
                tick="t1",
                units_running=[],
                head=HEAD,
                base=BASE,
                reused=reused,
            ),
        )
    passed, output = run_or_reuse(
        ledger,
        ReuseContext(unit=unit().id, head=HEAD, base=BASE),
        merged_since=lambda started: False,
        run=lambda: (True, ""),
        log=lambda line: None,
    )
    assert not passed
    return output


def test_the_checks_hold_the_unit_at_the_second_reuse_and_run_no_fix_agent(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.unit_test_output = reuse_output(tmp_path / "ledger", earlier_reuses=1)

    outcome = build(tmp_path, recorder)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.cause, stored.held_by) == (
        HELD,
        Cause.NEEDS_HUMAN,
        HeldBy.CHECKS,
    )
    assert all(text in stored.note for text in (TEST, HEAD, BASE))
    assert "requeue with a rework note" in stored.note
    assert stored.feedback == "", "nothing is saved for a fix agent"
    assert "claude:fix_checks" not in recorder.events
    assert "review" not in recorder.events and "push" not in recorder.events


def test_the_checks_treat_the_first_reuse_as_a_failure_for_a_fix_agent(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.unit_test_results = [
        (False, reuse_output(tmp_path / "ledger", earlier_reuses=0)),
        (True, ""),
    ]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("claude:fix_checks") == 1
