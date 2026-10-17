"""A failing test of a scheduled split's run is recorded with that split and fixed by one
change, and the open fix holds only the runs that execute that split (spec: e2e-failures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_e2e_gate
from tests.e2e_gate_fakes import open_fix
from tests.pipeline.test_e2e_split_groups import ACP, CLAUDE, PLAIN, Groups
from tests.pipeline.test_flake_fix_change import changes, waits_on
from tests.pipeline.test_scheduled_e2e_failure import wired
from tests.scheduled_e2e_fakes import ScheduledRun

# The test each split of the fixture repository holds.
TESTS = {"rest": PLAIN, "acp": ACP, "claude_code": CLAUDE}


def gated(run: ScheduledRun) -> ScheduledRun:
    """The run with the record of failures, and the gate the scheduled unit waits at."""
    return wired(
        run,
        on_e2e_gate=build_on_e2e_gate(run.store, run.inst, log=run.log.append),
        e2e_runs_whole=lambda *, cwd, base: True,
    )


@pytest.mark.parametrize("split", ["rest", "acp", "claude_code"])
def test_a_failing_test_of_the_split_is_recorded_with_it_and_fixed_by_one_change(
    tmp_path: Path, split: str
) -> None:
    run = gated(
        ScheduledRun(
            tmp_path,
            split=split,
            declared=True,
            make_ran=lambda tree: Groups(failing=TESTS.values()),
        )
    )

    outcome = run.tick()

    assert outcome.status == RunStatus.HELD
    (entry,) = preexisting_record(run.inst).entries()
    assert (entry.test, entry.split) == (TESTS[split], split)
    (fix,) = [c for c in changes(run.inst) if c.startswith("fix-failing")]
    assert waits_on(run.inst, run.subject.change) == [fix]
    assert (run.stored.state, run.stored.cause) == (PLANNED, Cause.GATED)


@pytest.mark.parametrize("split", ["rest", "acp", "claude_code"])
def test_an_open_fix_holds_the_run_of_its_split_and_no_other(tmp_path: Path, split: str) -> None:
    others = gated(ScheduledRun(tmp_path / "others", split=split, declared=True))
    for other in TESTS.keys() - {split}:
        open_fix(others.store, others.inst, TESTS[other], split=other)
    own = gated(ScheduledRun(tmp_path / "own", split=split, declared=True))
    fix = open_fix(own.store, own.inst, TESTS[split], split=split)

    free, held = others.tick(), own.tick()

    assert free.status == RunStatus.SATISFIED, "the fixes of the other splits do not hold it"
    assert others.ran.commands != []
    assert waits_on(others.inst, others.subject.change) == []
    assert held.status == RunStatus.HELD
    assert own.ran.commands == []
    assert waits_on(own.inst, own.subject.change) == [fix]
