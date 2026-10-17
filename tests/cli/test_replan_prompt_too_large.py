"""A planner prompt that is too large is an ordinary planning failure: it counts attempts, shows
as `failing n/3: <reason>` and is planned again by `abk replan --failed`
(spec: planner-in-flight)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan, tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "feature"


def listing(run: Replan, capsys: pytest.CaptureFixture[str]) -> str:
    _, out = run.run(capsys)
    return next(line for line in out.splitlines() if CHANGE in line)


def test_a_prompt_that_is_too_large_counts_attempts_gives_up_and_is_planned_again_by_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1) + "- [ ] 1.3 " + "x" * 2_100_000 + "\n")

    code, _ = run.run(capsys, CHANGE)

    assert code == 1
    assert run.calls == 0
    reason = run.records[CHANGE]["reason"]
    assert reason.startswith("the ")
    assert "for feature" in reason
    assert " bytes;" in reason
    assert "at most 2000000" in reason
    assert "OSError" not in reason
    assert "PlannerError" not in reason
    assert f"failing 1/3: {reason}" in listing(run, capsys)

    cli.plan_all(run.inst, store=run.store)
    assert f"failing 2/3: {reason}" in listing(run, capsys)

    cli.plan_all(run.inst, store=run.store)
    assert "given up" in listing(run, capsys)

    code, _ = run.run(capsys, "--failed")

    assert code == 1
    assert run.records[CHANGE]["attempts"] == 1
    assert run.calls == 0
