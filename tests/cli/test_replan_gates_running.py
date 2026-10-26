"""`abk replan` says a kept `running` unit no process holds is gated when a dependency the new plan
gives it is unmet (spec: resume-gating), and leaves it `planned`/`gated`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_replan_that_adds_an_unmet_dependency_gates_the_running_unit_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "has_thread", lambda _inst, _uid: True)
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1), dep=tasks_md(1))
    run.store.upsert(
        [
            stored_unit("dep/1", change="dep", repo="platform", groups=(1,)),
            stored_unit("feature/1", change="feature", groups=(1,)),
        ]
    )
    run.store.set_state("dep/1", IN_REVIEW, pr=3, branch="spec/dep/1")
    run.store.set_state("feature/1", RUNNING, branch="spec/feature/1")

    reply = answer(planned("feature/1", (1,), depends_on=("dep/1",)))
    code, out = run.run(capsys, "feature", reply=reply)

    assert code == 0
    assert "gated: feature/1 waits for dep group 1" in out
    unit = run.store.get("feature/1")
    assert (unit.state, unit.cause) == (PLANNED, Cause.GATED)
