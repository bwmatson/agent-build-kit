"""A test of how the acp adapter ends a run must not depend on how long the machine takes.

The test that an agent leaving stderr held has that holder killed once failed in a loaded
suite on a bound of wall-clock seconds around the run. It runs here in a child pytest whose
clock, as that module reads it, says each run took far longer than that bound: a loaded
machine without waiting for one. The test passes whatever the clock says, or it is racy.
"""

from __future__ import annotations

import pytest

from tests.child_pytest import run_scenario
from tests.tracked_files import ROOT

MODULE = f"{ROOT}/tests/runtimes/test_acp_outcome.py"
RUN_BOUNDED_TESTS = (
    "test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed",
    "test_an_agent_that_leaves_a_process_holding_its_pipes_still_ends_the_run",
    "test_a_process_out_of_reach_of_the_kill_does_not_hold_the_run_open",
)


@pytest.mark.parametrize("name", RUN_BOUNDED_TESTS)
def test_a_test_that_runs_the_adapter_passes_when_the_run_seems_to_take_long(
    name: str, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_scenario(
        pytester,
        "loaded_machine",
        f"{MODULE}::{name}",
        "-p",
        "tests.child_modules.loaded_machine.skewed_clock",
        "-rA",
        monkeypatch=monkeypatch,
    )

    assert run.code == 0, run.output
    # The two reads of `_run_bounded`: without them the skew proves nothing.
    skewed = int(run.output.split("skewed reads: ")[1].split()[0])
    assert skewed >= 2, run.output
    assert "PASSED" in run.output, run.output
