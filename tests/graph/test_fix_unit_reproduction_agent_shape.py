"""A unit of a fix change the regression agent wrote is checked for its test before it builds,
whatever its group is titled (spec: fix-unit-reproduction, regression-agent)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.fix_reproduction import Outcome
from tests.graph.test_fix_unit_reproduction import CHANGE, TEST, Asked, built, fix_unit
from tests.graph_driver import tick
from tests.regression_agent_support import write_change


def test_a_fix_unit_written_by_the_agent_reaches_the_reproduction_check(tmp_path: Path) -> None:
    installation, recorder, subject = fix_unit(tmp_path)
    # The files exactly as the stand-in agent writes them: a group titled for the fix, and the
    # test named on a line of the proposal.
    write_change(installation.changes_dir / CHANGE)
    answer = Asked(Outcome.FAILS)

    tick(tmp_path, recorder, subject=subject, reproduce_test=answer)

    assert answer.calls == [(TEST, 5)]
    assert built(recorder)
