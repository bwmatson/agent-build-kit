"""`abk status` prints one line for each stale plan, naming the change and why, and none for a
current plan, including for a plan that waits for an outage (plan-migration)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")


def status_lines(run: Replan, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0
    return [line for line in capsys.readouterr().out.splitlines() if "stale" in line]


def test_status_prints_a_line_for_each_stale_plan_naming_the_change_and_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1), beta=tasks_md(1), gamma=tasks_md(1))
    enable_review(run, ceilings={"full": 750})
    code, _ = run.run(capsys, "alpha", reply=answer(planned("alpha/1", (1,))))
    assert code == 0
    enable_review(run, ceilings={"full": 900})
    code, _ = run.run(capsys, "gamma", reply=answer(planned("gamma/1", (1,))))
    assert code == 0
    run.record("beta")

    lines = status_lines(run, capsys)

    assert len(lines) == 2
    assert any("alpha" in line and "ceilings changed" in line for line in lines)
    assert any("beta" in line and "planned before the review policy" in line for line in lines)
    assert not any("gamma" in line for line in lines), "gamma was re-planned and is current"
    assert not any("alpha" in line and "beta" in line for line in lines), "one line each"


def test_status_prints_the_line_of_a_stale_plan_that_waits_for_an_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run, ceilings={"full": 750})
    code, _ = run.run(capsys, "alpha", reply=answer(planned("alpha/1", (1,))))
    assert code == 0
    standing = run.records["alpha"]["sizing"]
    run.record("alpha", ok=False, attempts=1, waiting="network", sizing=standing)
    enable_review(run, ceilings={"full": 900})

    lines = status_lines(run, capsys)

    assert any("alpha" in line and "ceilings changed" in line for line in lines)
