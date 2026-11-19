"""`abk status` prints one line for each stale plan, naming the change and why, and none for a
current plan, including for a plan that waits for an outage (plan-migration)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.shell import git_out as git
from agent_build_kit.pipeline.units import UnitState
from tests.cli.plan_outage_fakes import raises, service
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md
from tests.factories import commit_files, init_repo, stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def status_lines(run: Replan, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0
    return [line for line in capsys.readouterr().out.splitlines() if "stale" in line]


def test_status_prints_a_line_for_each_stale_plan_naming_the_change_and_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
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
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run, ceilings={"full": 750})
    code, _ = run.run(capsys, "alpha", reply=answer(planned("alpha/1", (1,))))
    assert code == 0
    enable_review(run, ceilings={"full": 900})
    run.runtime.act = raises(service())

    code, _ = run.run(capsys, "alpha")

    assert code == 1
    assert run.records["alpha"]["waiting"] == "service"
    assert run.records["alpha"].get("attempts", 0) == 0, "an outage uses no attempt"
    lines = status_lines(run, capsys)
    assert any("alpha" in line and "ceilings changed" in line for line in lines)
    code, listing = run.run(capsys)
    assert code == 2
    assert "ceilings changed" in next(
        line for line in listing.splitlines() if line.startswith("alpha:")
    )


def test_a_waiting_first_plan_with_no_units_stored_is_not_called_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run, ceilings={"full": 750})
    run.record("alpha", ok=False, attempts=1, waiting="network", sizing="")

    assert cli.stale_plan_lines(run.inst) == []
    assert status_lines(run, capsys) == []


def test_status_warns_of_a_built_group_stored_with_a_mode_other_than_its_floor_and_of_no_other(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    tasks = (
        "# Tasks\n\nAcceptance: none — a fixture\n\n"
        "## 1. [app] [unit-test] Group 1\n\n- [ ] 1.1 Edit `tests/test_x.py` to cover it.\n\n"
        "## 2. [app] [unit-test] Group 2\n\n- [ ] 2.1 Edit `tests/test_y.py` to cover it.\n"
    )
    run = Replan(tmp_path, monkeypatch, feature=tasks)
    repo = init_repo(run.inst.checkouts["app"])
    commit_files(repo, "initial", {"README.md": "x"})
    git(repo, "switch", "-q", "-c", "spec/feature/1")
    commit_files(repo, "test: Group 1", {"tests/test_x.py": "x"})
    commit_files(repo, "feat: Group 1", {"src/x.py": "x"})
    commit_files(repo, "test: Group 2", {"tests/test_y.py": "y"})
    modes = {"feature/1": "tests_and_code", "feature/2": "tests_only"}
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1, 2), group_modes=modes)])
    run.store.set_state("feature/1", UnitState.RUNNING, branch="spec/feature/1")
    run.record("feature")
    capsys.readouterr()

    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0

    lines = [
        ln for ln in capsys.readouterr().out.splitlines() if "feature/1" in ln and "mode" in ln
    ]
    assert len(lines) == 1
    assert all(word in lines[0] for word in ("group 1", "tests_and_code", "tests_only"))
    assert "group 2" not in lines[0]


def test_a_waiting_plan_with_a_unit_stored_is_called_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run, ceilings={"full": 750})
    code, _ = run.run(capsys, "alpha", reply=answer(planned("alpha/1", (1,))))
    assert code == 0
    run.record("alpha", ok=False, attempts=1, waiting="network", sizing="")

    lines = cli.stale_plan_lines(run.inst)

    assert len(lines) == 1 and lines[0].startswith("alpha: plan is stale, ")
