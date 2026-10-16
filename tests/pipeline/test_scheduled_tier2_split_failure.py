"""A failing test of a scheduled split's run is recorded with that split and fixed by one
change, and the open fix holds only the runs that execute that split (spec: tier2-failures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.flakes import fix_change_name
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.untouched_failures import PREFIX, preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting, build_on_tier2_gate
from tests.factories import stored_unit
from tests.pipeline.test_flake_fix_change import changes, waits_on
from tests.pipeline.test_tier2_split_groups import ACP, CLAUDE, PLAIN, Groups
from tests.scheduled_tier2_fakes import ScheduledRun
from tests.tier2_wait_fakes import verdict_of

# The test each split of the fixture repository holds.
TESTS = {"rest": PLAIN, "acp": ACP, "claude_code": CLAUDE}


def wired(run: ScheduledRun) -> ScheduledRun:
    """The run with the record of failures, and the gate the scheduled unit waits at."""
    run.overrides["on_preexisting"] = build_on_preexisting(run.store, run.inst, log=run.log.append)
    run.overrides["on_tier2_gate"] = build_on_tier2_gate(run.store, run.inst, log=run.log.append)
    run.overrides["tier2_runs_whole"] = lambda *, cwd, base: True
    return run


def open_fix(run: ScheduledRun, split: str) -> str:
    """A failing test of `split` on the base, recorded and its fix change written, as a unit
    that did not wait leaves them."""
    tasks = run.inst.changes_dir / "feature" / "tasks.md"
    tasks.parent.mkdir(parents=True, exist_ok=True)
    tasks.write_text("# Tasks\n\n## 1. [app] [tier2] First\n\n- [ ] 1.1 Test: it\n")
    met = stored_unit("feature/1", change="feature", repo="app", groups=(1,))
    run.store.upsert([met])
    verdict = verdict_of(old=(TESTS[split],), group=split)
    build_on_preexisting(run.store, run.inst, log=run.log.append)(
        met, verdict, verdict.pre_existing[0], wait=False
    )
    fix = fix_change_name(TESTS[split], PREFIX)
    run.store.upsert([stored_unit(f"{fix}/1", change=fix, repo="app", groups=(1,))])
    return fix


@pytest.mark.parametrize("split", ["rest", "acp", "claude_code"])
def test_a_failing_test_of_the_split_is_recorded_with_it_and_fixed_by_one_change(
    tmp_path: Path, split: str
) -> None:
    run = wired(
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
    others = wired(ScheduledRun(tmp_path / "others", split=split, declared=True))
    for other in TESTS.keys() - {split}:
        open_fix(others, other)
    own = wired(ScheduledRun(tmp_path / "own", split=split, declared=True))
    fix = open_fix(own, split)

    free, held = others.tick(), own.tick()

    assert free.status == RunStatus.SATISFIED, "the fixes of the other splits do not hold it"
    assert others.ran.commands != []
    assert waits_on(others.inst, others.subject.change) == []
    assert held.status == RunStatus.HELD
    assert own.ran.commands == []
    assert waits_on(own.inst, own.subject.change) == [fix]
