"""A start on an estimate is kept under the id of the unit started, through the real gates.

The round's own decision, the resume time and the status ask the guard too, but start
nothing, so they use no allowance and no slot of the cap. The gate the runner asks before
each agent step names the unit it is for (`starting`), and a track names itself.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline.usage_guard import decide_start, starting
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, UsageRecord, append_record
from agent_build_kit.pipeline.wiring import build_usage_gate
from tests.conftest import make_installation
from tests.graph_driver import fresh, tick
from tests.usage_host import Host, configure, payload, refused

MINUTE = timedelta(minutes=1)


def refused_with_room(host: Host, *, session: float = 70.0, limits: bool = True) -> None:
    """A reading three hours old, the session at `session`% against 92, and a refusal just now."""
    if limits:
        configure(session={"usage_pause_pct": 92}, weekly={"usage_pause_pct": 80})
    host.keep_reading(180 * MINUTE, payload(session=session, weekly=6.0))
    refused(host, cooling=3 * MINUTE)


def admitted(host: Host) -> list[str]:
    return json.loads(host.cache.read_text()).get("estimate_units", [])


def test_asks_that_start_nothing_admit_no_unit(host: Host) -> None:
    refused_with_room(host)
    _, resume_at = build_usage_gate()

    assert decide_start().may_start
    resume_at()

    assert admitted(host) == []


def test_the_gate_admits_exactly_the_units_started_and_refuses_a_fourth(host: Host) -> None:
    refused_with_room(host)
    configure(
        session={"usage_pause_pct": 92, "usage_unit_allowance_pct": 1},
        weekly={"usage_pause_pct": 80},
    )
    may_start, _ = build_usage_gate()

    answers = []
    for n in (1, 2, 3, 4):
        assert decide_start().may_start or n == 4  # the round's own ask, naming no unit
        with starting(f"feature/{n}"):
            answers.append(may_start()[0])

    assert answers == [True, True, True, False]
    assert admitted(host) == ["feature/1", "feature/2", "feature/3"]


def test_a_started_unit_counts_once_when_its_ledger_record_arrives(host: Host) -> None:
    """Session 70% and ten points a unit: one unit is 80, and two would be 90 plus the margin."""
    refused_with_room(host)
    may_start, _ = build_usage_gate()
    assert decide_start().may_start
    with starting("feature/1"):
        assert may_start()[0]
    at = datetime.now().astimezone() - 5 * MINUTE
    append_record(
        host.cache.parent / LEDGER_NAME,
        UsageRecord(at=at.isoformat(), unit="feature/1", node="implement"),
    )

    with starting("feature/1"):
        allowed, why = may_start()

    assert allowed
    assert "session ~80% estimated (70% read + 10% spent)" in why


def test_the_runner_s_gate_before_an_agent_step_names_the_unit(tmp_path: Path, host: Host) -> None:
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    refused_with_room(host, session=40.0, limits=False)
    may_start, _ = build_usage_gate()

    tick(tmp_path, fresh(tmp_path), may_start=may_start)

    assert admitted(host) == ["add-marker/1"]
