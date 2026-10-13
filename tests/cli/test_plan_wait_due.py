"""A waiting plan is tried again when its time has passed, and not before (spec: unit-scheduling).

Until then `plan_all` makes no planner call and a round does not count it as work, so the
usage guard is not asked for it. A success, an ordinary failure and an edit of `tasks.md`
each end the wait.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.plan_outage_fakes import moment, network, raises
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit
from tests.fake_clock import FakeClock, install
from tests.usage_host import Host, payload

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "feature"
WAIT_FIELDS = ("waiting", "waits", "since", "until", "reason")
GOOD = answer(planned("feature/1", (1,)))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    return Replan(tmp_path, monkeypatch, feature=tasks_md(1))


def wait(run: Replan, clock: FakeClock, *, minutes: int = 5, **fields) -> None:
    """The change as a wait left it: one failed attempt, and the next try `minutes` on."""
    run.record(
        CHANGE,
        ok=False,
        attempts=1,
        waiting="network",
        waits=2,
        since=(clock.now() - timedelta(minutes=3)).isoformat(),
        until=(clock.now() + timedelta(minutes=minutes)).isoformat(),
        reason="API Error: Can't reach the API server",
        **fields,
    )


def plan(run: Replan) -> cli.PlanResult:
    return cli.plan_all(run.inst, store=run.store)[CHANGE]


def test_a_wait_with_its_time_ahead_is_skipped_with_no_planner_call(
    run: Replan, clock: FakeClock
) -> None:
    wait(run, clock)
    before = run.records[CHANGE]

    assert plan(run).status == "skipped"

    assert run.calls == 0
    assert run.records[CHANGE] == before


def test_once_its_time_has_passed_the_change_is_planned_and_a_success_ends_the_wait(
    run: Replan, clock: FakeClock
) -> None:
    wait(run, clock)
    clock.advance(5 * 60 + 1)
    run.runtime.answer = GOOD

    assert plan(run).status == "planned"

    record = run.records[CHANGE]
    assert record["ok"] is True
    assert record["attempts"] == 1
    assert not any(field in record for field in WAIT_FIELDS)


def test_an_ordinary_failure_ends_the_wait_and_adds_one_attempt(
    run: Replan, clock: FakeClock
) -> None:
    wait(run, clock)
    clock.advance(5 * 60 + 1)
    run.runtime.act = raises(ValueError("the reply could not be read"))

    assert plan(run).status == "failed"

    record = run.records[CHANGE]
    assert (record["attempts"], record["ok"]) == (2, False)
    assert not any(field in record for field in ("waiting", "waits", "since", "until"))
    assert record["reason"] == "ValueError: the reply could not be read"


def test_an_edit_of_tasks_md_starts_the_record_over(run: Replan, clock: FakeClock) -> None:
    wait(run, clock)
    run.write(CHANGE, tasks_md(2))
    run.runtime.act = raises(network())

    assert plan(run).status == "waiting"

    record = run.records[CHANGE]
    assert (record["attempts"], record["waits"]) == (0, 1)
    assert moment(record["since"]) == clock.now()
    assert run.calls == 1


def test_a_round_whose_only_candidate_waits_asks_the_guard_for_nothing(
    run: Replan, clock: FakeClock, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)
    run.runtime.supports_usage_tracking = True
    host.keep_in(run.inst.state_dir)
    host.answers = [payload(session=10.0)]
    run.store.upsert([stored_unit("other/1", change="other")])
    wait(run, clock)

    ready = cli.run_round(
        run.inst,
        run.store,
        building=set(),
        started=set(),
        only=frozenset({"nothing/1"}),
        submit=True,
    )

    assert ready == []
    assert host.asked == 0
