"""`abk replan` and `abk status` say a plan waits for an outage, is given up with the command
to plan it again, or is failing with its reason (spec: unit-scheduling).

The planner is the runtime stand-in and the clock is replaced, so the times printed are the
ones the record holds.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.plan_outage_fakes import clock_time, network, raises, service
from tests.cli.replan_driver import Replan, tasks_md
from tests.fake_clock import FakeClock, install

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "feature"
SINCE = "2030-01-01T09:00:00+00:00"
UNTIL = "2030-01-01T09:05:00+00:00"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    return Replan(tmp_path, monkeypatch, feature=tasks_md(1), other=tasks_md(1))


def waiting(run: Replan, kind: str = "network", **fields) -> None:
    run.record(
        CHANGE,
        ok=False,
        attempts=1,
        waiting=kind,
        waits=2,
        since=SINCE,
        until=UNTIL,
        reason="API Error: Can't reach the API server",
        **fields,
    )


def line_of(out: str, change: str = CHANGE) -> str:
    return next(line for line in out.splitlines() if line.startswith(f"{change}:"))


@pytest.mark.parametrize(
    ("kind", "phrase"),
    [("network", "the network"), ("service", "the model service")],
)
def test_a_bare_replan_lists_a_waiting_plan_by_its_cause(
    run: Replan, clock: FakeClock, capsys: pytest.CaptureFixture[str], kind: str, phrase: str
) -> None:
    waiting(run, kind)

    code, out = run.run(capsys)

    assert code == 2
    assert line_of(out) == (
        f"feature: waiting for {phrase} since {clock_time(SINCE)}, "
        f"next try {clock_time(UNTIL)} (attempts 1/3, not used)"
    )


def test_a_spent_plan_is_given_up_with_the_command_and_a_failing_one_shows_its_reason(
    run: Replan, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    run.record(CHANGE, ok=False, attempts=3, reason="the graph call failed: boom")
    run.record("other", ok=False, attempts=1, reason="ValueError: bad reply")

    _, out = run.run(capsys)

    assert "given up" in line_of(out)
    assert "abk replan --failed" in line_of(out)
    assert line_of(out, "other") == "other: failing 1/3: ValueError: bad reply"


@pytest.mark.parametrize(
    ("error", "phrase"), [(network(), "the network"), (service(), "the model service")]
)
def test_replan_of_a_change_that_meets_the_outage_says_it_waits_and_used_no_attempt(
    run: Replan,
    clock: FakeClock,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    phrase: str,
) -> None:
    waiting(run)
    run.runtime.act = raises(error)

    code, out = run.run(capsys, CHANGE)

    assert code == 1
    assert run.calls == 1
    record = run.records[CHANGE]
    assert record["waits"] == 1
    assert (
        f"feature: waiting for {phrase} — no attempt used; next try {clock_time(record['until'])}"
    ) in out
    assert "the plan failed" not in out


def test_failed_selects_a_waiting_plan(
    run: Replan, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    waiting(run)
    run.runtime.act = raises(network())

    code, out = run.run(capsys, "--failed")

    assert code == 1
    assert run.calls == 1
    assert "feature: waiting for the network" in out


def test_forget_removes_a_waiting_record_and_the_next_wait_counts_from_one(
    run: Replan, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    waiting(run)

    code, _ = run.run(capsys, CHANGE, "--forget")
    assert code == 0
    assert CHANGE not in run.records

    run.runtime.act = raises(network())
    cli.plan_all(run.inst, store=run.store, only={CHANGE})
    assert (run.records[CHANGE]["waits"], run.records[CHANGE]["attempts"]) == (1, 0)


def test_status_lists_the_waiting_change_by_cause(
    run: Replan,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    waiting(run, "service")
    capsys.readouterr()

    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0

    shown = [line for line in capsys.readouterr().out.splitlines() if CHANGE in line]
    assert any("waiting for the model service" in line for line in shown)
    assert not any("failing" in line or "given up" in line for line in shown)


def test_a_waiting_record_missing_its_times_is_still_listed(
    run: Replan, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    run.record(CHANGE, ok=False, attempts=1, waiting="network")

    code, out = run.run(capsys)

    assert code == 2
    assert line_of(out) == "feature: waiting for the network (attempts 1/3, not used)"
