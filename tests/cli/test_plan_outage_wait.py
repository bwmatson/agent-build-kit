"""A planner call that ends on an outage is a wait, not an attempt (spec: unit-scheduling).

The runtime stand-in raises the typed errors from inside `run`; the clock is replaced and
the probe is replaced at the seam the step handler reads it through. A strong sign or a
status waits on its own evidence, a weak one as the probe's two groups say, and a probe
that errors counts as no outage.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.network_probe import Reachability
from agent_build_kit.runtimes import AgentRateLimited
from tests.cli.plan_outage_fakes import MINUTE, moment, network, raises, service
from tests.cli.replan_driver import Replan, tasks_md
from tests.fake_clock import FakeClock, install
from tests.pipeline.test_network_outage_parking import Probe

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "feature"
WAIT_FIELDS = ("waiting", "waits", "since", "until")
CAP = {"service_unavailable_attempts": 3}


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Probe:
    return Probe(monkeypatch)


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    return Replan(tmp_path, monkeypatch, feature=tasks_md(1))


def plan(run: Replan, error: Exception) -> cli.PlanResult:
    run.runtime.act = raises(error)
    return cli.plan_all(run.inst, store=run.store)[CHANGE]


def test_a_network_outage_records_a_wait_and_no_attempt(run: Replan, clock: FakeClock) -> None:
    result = plan(run, network())

    assert result.status == "waiting"
    record = run.records[CHANGE]
    assert record["ok"] is False
    assert record["waiting"] == "network"
    assert record["waits"] == 1
    assert record["attempts"] == 0
    assert moment(record["since"]) == clock.now()
    assert moment(record["until"]) == clock.now() + MINUTE
    assert "EAI_AGAIN" in record["reason"]
    assert run.store.all() == []


def test_a_wait_keeps_the_attempt_a_failure_on_the_same_text_had(
    run: Replan, clock: FakeClock
) -> None:
    run.record(CHANGE, ok=False, attempts=1)

    assert plan(run, network()).status == "waiting"

    record = run.records[CHANGE]
    assert (record["attempts"], record["waits"], record["ok"]) == (1, 1, False)


def test_three_waits_in_a_row_use_no_attempt_and_back_off_one_two_then_five_minutes(
    run: Replan, clock: FakeClock
) -> None:
    first = clock.now()
    backoffs: list[timedelta] = []
    for _ in range(3):
        assert plan(run, network()).status == "waiting"
        until = moment(run.records[CHANGE]["until"])
        backoffs.append(until - clock.now())
        clock.advance((until - clock.now()).total_seconds() + 1)

    record = run.records[CHANGE]
    assert backoffs == [MINUTE, 2 * MINUTE, 5 * MINUTE]
    assert (record["attempts"], record["waits"]) == (0, 3)
    assert moment(record["since"]) == first
    assert run.calls == 3


@pytest.mark.parametrize(
    ("reached", "waiting"),
    [
        (Reachability(api=False, control=False), "network"),
        (Reachability(api=False, control=True), "service"),
    ],
)
def test_a_weak_sign_waits_as_the_probes_two_groups_say(
    run: Replan, clock: FakeClock, probe: Probe, reached: Reachability, waiting: str
) -> None:
    probe.answer = reached

    assert plan(run, network("weak")).status == "waiting"

    record = run.records[CHANGE]
    assert (record["waiting"], record["attempts"]) == (waiting, 0)
    assert probe.asked == ["api.example.test"]


@pytest.mark.parametrize(
    "answer", [Reachability(api=True, control=True), RuntimeError("the probe broke")]
)
def test_a_weak_sign_with_the_host_reachable_or_a_probe_that_errors_is_an_ordinary_failure(
    run: Replan, clock: FakeClock, probe: Probe, answer: Reachability | Exception
) -> None:
    probe.answer = answer

    assert plan(run, network("weak")).status == "failed"

    record = run.records[CHANGE]
    assert record["attempts"] == 1
    assert record["ok"] is False
    assert "waiting" not in record
    assert "EAI_AGAIN" in record["reason"]


def test_a_strong_sign_waits_whatever_the_probe_says(
    run: Replan, clock: FakeClock, probe: Probe
) -> None:
    probe.answer = Reachability(api=True, control=True)

    assert plan(run, network("strong")).status == "waiting"

    assert run.records[CHANGE]["waiting"] == "network"
    assert probe.asked == []


def test_a_rate_limit_is_recorded_as_a_failure_and_not_as_a_wait(
    run: Replan, clock: FakeClock, probe: Probe
) -> None:
    assert plan(run, AgentRateLimited("usage limit reached")).status == "failed"

    record = run.records[CHANGE]
    assert record["attempts"] == 1
    assert "waiting" not in record
    assert record["reason"].startswith("AgentRateLimited: usage limit reached")
    assert probe.asked == []


def test_a_status_waits_for_the_service_without_asking_the_probe(
    run: Replan, clock: FakeClock, probe: Probe
) -> None:
    assert plan(run, service()).status == "waiting"

    record = run.records[CHANGE]
    assert (record["waiting"], record["waits"], record["attempts"]) == ("service", 1, 0)
    assert "529" in record["reason"]
    assert probe.asked == []


def test_the_status_wait_is_capped_and_the_next_failure_counts_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock, probe: Probe
) -> None:
    run = Replan(tmp_path, monkeypatch, limits=CAP, feature=tasks_md(1))
    for waits in (1, 2, 3):
        assert plan(run, service()).status == "waiting"
        assert run.records[CHANGE]["waits"] == waits
        clock.advance(31 * 60)

    assert plan(run, service()).status == "failed"

    record = run.records[CHANGE]
    assert record["attempts"] == 1
    assert record["ok"] is False
    assert not any(field in record for field in WAIT_FIELDS)
    assert "529" in record["reason"]


def test_a_wait_found_by_the_probe_is_not_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock, probe: Probe
) -> None:
    run = Replan(tmp_path, monkeypatch, limits=CAP, feature=tasks_md(1))
    probe.answer = Reachability(api=False, control=True)

    for waits in range(1, 6):
        assert plan(run, network("weak")).status == "waiting"
        assert run.records[CHANGE]["waits"] == waits
        clock.advance(31 * 60)

    assert (run.records[CHANGE]["waiting"], run.records[CHANGE]["attempts"]) == ("service", 0)


def marker(run: Replan) -> dict:
    return json.loads((run.inst.state_dir / "paused.json").read_text())


def test_a_network_wait_writes_the_network_pause_naming_the_change(
    run: Replan, clock: FakeClock
) -> None:
    plan(run, network())

    assert marker(run)["kind"] == "network"
    assert CHANGE in marker(run)["reason"]


def test_a_network_wait_does_not_replace_a_pause_that_stands(run: Replan, clock: FakeClock) -> None:
    standing = {
        "until": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        "reason": "network unreachable during other/1",
        "kind": "network",
        "at": datetime.now(UTC).isoformat(),
    }
    (run.inst.state_dir / "paused.json").write_text(json.dumps(standing))

    plan(run, network())

    assert marker(run)["until"] == standing["until"]
    assert marker(run)["reason"] == standing["reason"]
    assert run.records[CHANGE]["waiting"] == "network"


def test_a_service_wait_writes_no_pause(run: Replan, clock: FakeClock) -> None:
    plan(run, service())

    assert run.records[CHANGE]["waiting"] == "service"
    assert not (run.inst.state_dir / "paused.json").exists()


def test_waits_the_network_made_do_not_count_toward_the_status_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock, probe: Probe
) -> None:
    run = Replan(tmp_path, monkeypatch, limits=CAP, feature=tasks_md(1))
    for _ in range(4):
        assert plan(run, network()).status == "waiting"
        clock.advance(31 * 60)
    for _ in range(3):
        assert plan(run, service()).status == "waiting"
        clock.advance(31 * 60)
    record = run.records[CHANGE]
    assert (record["waiting"], record["attempts"], record["waits"]) == ("service", 0, 7)

    assert plan(run, service()).status == "failed"

    record = run.records[CHANGE]
    assert record["attempts"] == 1
    assert not any(field in record for field in WAIT_FIELDS)


def test_a_network_wait_leaves_the_other_changes_for_the_tick_that_clears_the_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1), other=tasks_md(1))

    results = plan_all_of(run, network())

    assert sorted(results) == ["feature", "other"]
    assert sorted(r.status for r in results.values()) == ["skipped", "waiting"]
    assert run.calls == 1
    assert len(run.records) == 1


def plan_all_of(run: Replan, error: Exception) -> dict[str, cli.PlanResult]:
    run.runtime.act = raises(error)
    return cli.plan_all(run.inst, store=run.store)
