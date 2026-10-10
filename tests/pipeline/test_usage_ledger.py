"""The ledger's reader: one record per unit, node, round and session, the last
one written; lines from before a field existed still load (spec:
agent-usage-capture, a resumed or re-run call is counted once).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_ledger import (
    UsageRecord,
    forget_told,
    read_ledger,
    record_call,
)


def spend(record: UsageRecord) -> float | None:
    """The call's own spend, as the report sums it."""
    return record.cost.incremental_usd if record.cost else None


def line(**fields) -> dict:
    """A ledger line as written now: a call's own spend is in its `cost` object."""
    flat = {**_flat_line(), **fields}
    own = flat.pop("cost_usd", None)
    theirs = flat.pop("reported_cost_usd", None)
    return flat | {"cost": {"incremental_usd": own, "basis": "reported", "reported_usd": theirs}}


def _flat_line(**fields) -> dict:
    return {
        "kind": "agent",
        "at": "2026-01-01T10:00:00+00:00",
        "unit": "add-marker/1",
        "node": "implement",
        "round": 0,
        "role": "implement",
        "model": "m",
        "runtime": "claude_code",
        "session_id": "sess-1",
        "input_tokens": 10,
        "output_tokens": 20,
        "cost_usd": 0.5,
        "usage_source": "reported",
        **fields,
    }


def write(path: Path, *lines: dict | str) -> Path:
    path.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines))
    return path


def test_the_same_node_and_round_written_twice_is_counted_once_with_the_latest_figures(
    tmp_path: Path,
) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(cost_usd=0.5, at="2026-01-01T10:00:00+00:00"),
        line(node="review", round=1, role="review", session_id="sess-2"),
        line(cost_usd=0.9, at="2026-01-01T10:30:00+00:00"),
    )

    records = read_ledger(ledger)

    assert len(records) == 2
    (build,) = [r for r in records if r.node == "implement"]
    assert spend(build) == 0.9
    assert sum(spend(r) or 0 for r in records) == 0.9 + 0.5


def test_a_round_of_the_same_node_is_its_own_record(tmp_path: Path) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(node="review", round=1, role="review"),
        line(node="review", round=2, role="review"),
    )

    assert [r.round for r in read_ledger(ledger)] == [1, 2]


def test_a_node_re_run_in_a_new_session_is_counted_once_with_the_latest_figures(
    tmp_path: Path,
) -> None:
    """The session id is an attribute of a record, not part of its key: a node and round that
    ran again, in whichever session, is one call."""
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(node="fix_checks", round=1, session_id="sess-1", cost_usd=0.5),
        line(node="fix_checks", round=1, session_id="sess-2", cost_usd=0.7),
    )

    (record,) = read_ledger(ledger)

    assert (record.session_id, spend(record)) == ("sess-2", 0.7)


def test_a_fix_continuing_the_build_session_is_the_fixs_spend_and_not_the_builds(
    tmp_path: Path,
) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(node="implement", round=0, session_id="S", cost_usd=0.50),
        line(node="fix_checks", round=1, session_id="S", resumed=True, cost_usd=0.08),
        line(node="fix_checks", round=2, session_id="S", resumed=True, cost_usd=0.06),
    )

    records = read_ledger(ledger)

    assert {(r.node, r.round): spend(r) for r in records} == {
        ("implement", 0): 0.50,
        ("fix_checks", 1): 0.08,
        ("fix_checks", 2): 0.06,
    }
    assert {r.session_id for r in records} == {"S"}, "one session id under several nodes"


def test_a_fix_that_ran_twice_after_the_build_in_one_session_is_counted_once(
    tmp_path: Path,
) -> None:
    """A fix killed after its call was recorded and run again continues the build session
    again; it is a re-run of its own call, and must not add to what `implement` spent."""
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(node="implement", round=0, session_id="S", cost_usd=0.50),
        line(node="fix_checks", round=1, session_id="S", resumed=True, cost_usd=0.08),
        line(node="fix_checks", round=1, session_id="S", resumed=True, cost_usd=0.09),
    )

    records = read_ledger(ledger)

    assert {r.node: spend(r) for r in records if r.node == "implement"} == {"implement": 0.50}
    assert sum(spend(r) or 0 for r in records if r.node == "fix_checks") == pytest.approx(0.17)


def test_a_crash_resume_of_the_same_node_still_adds_to_the_call_it_resumed(
    tmp_path: Path,
) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(node="fix_checks", round=1, session_id="S", resumed=False, cost_usd=0.08),
        line(node="implement", round=0, session_id="S", resumed=True, cost_usd=0.50),
        line(node="fix_checks", round=1, session_id="S", resumed=True, cost_usd=0.02),
    )

    by_node = {r.node: spend(r) for r in read_ledger(ledger)}

    assert by_node["fix_checks"] == pytest.approx(0.10)
    assert by_node["implement"] == 0.50, "another node's resumed call is not folded in"


def test_a_resumed_call_adds_to_the_call_it_resumed_and_a_rerun_replaces_it(
    tmp_path: Path,
) -> None:
    resumed = write(
        tmp_path / "resumed.jsonl",
        line(node="review", round=1, session_id="S", resumed=False, cost_usd=0.40),
        line(node="review", round=1, session_id="S", resumed=True, cost_usd=0.05),
    )
    rerun = write(
        tmp_path / "rerun.jsonl",
        line(node="review", round=1, session_id="S", resumed=False, cost_usd=0.40),
        line(node="review", round=1, session_id="S", resumed=False, cost_usd=0.05),
    )

    assert sum(spend(r) or 0 for r in read_ledger(resumed)) == pytest.approx(0.45)
    assert sum(spend(r) or 0 for r in read_ledger(rerun)) == 0.05


def test_a_resumed_call_adds_what_the_agent_reported_beside_the_gateways_figures_too(
    tmp_path: Path,
) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(
            session_id="S",
            usage_source="gateway",
            reported={"input_tokens": 9, "output_tokens": None},
            reported_cost_usd=0.4,
        ),
        line(
            session_id="S",
            resumed=True,
            usage_source="gateway",
            reported={"input_tokens": 1, "output_tokens": None},
            reported_cost_usd=0.1,
        ),
    )

    (record,) = read_ledger(ledger)

    assert record.reported is not None
    assert record.reported.input_tokens == 10
    assert record.reported.output_tokens is None
    assert record.cost is not None
    assert record.cost.reported_usd == pytest.approx(0.5)


def test_calls_with_no_session_id_in_one_node_and_round_are_each_counted(tmp_path: Path) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(session_id=None, cost_usd=0.2, at="2026-01-01T10:00:00+00:00"),
        line(session_id=None, cost_usd=0.3, at="2026-01-01T10:05:00+00:00"),
    )

    assert sum(spend(r) or 0 for r in read_ledger(ledger)) == 0.5


def test_a_line_from_before_a_field_existed_loads_with_that_field_absent(tmp_path: Path) -> None:
    old = {
        "at": "2025-06-01T09:00:00+00:00",
        "unit": "add-marker/1",
        "node": "implement",
        "round": 0,
        "role": "implement",
        "model": "m",
        "runtime": "claude_code",
        "cost_usd": 0.25,
        "usage_source": "reported",
    }
    ledger = write(tmp_path / "usage-ledger.jsonl", old)

    (record,) = read_ledger(ledger)

    assert record.cost is not None
    assert record.cost.legacy_usd == 0.25
    assert record.cost.incremental_usd is None
    assert record.input_tokens is None
    assert record.cache_read_input_tokens is None
    assert record.duration_ms is None


def test_a_line_with_a_field_a_later_version_adds_still_loads(tmp_path: Path) -> None:
    ledger = write(tmp_path / "usage-ledger.jsonl", line(a_later_field={"x": [1]}))

    (record,) = read_ledger(ledger)

    assert spend(record) == 0.5


def test_a_missing_ledger_reads_as_empty(tmp_path: Path) -> None:
    assert read_ledger(tmp_path / "none-yet.jsonl") == []


def test_a_half_written_line_costs_only_itself(tmp_path: Path) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(),
        '{"kind": "agent", "at": "2026-01-01T10:',
        line(node="review", round=1, role="review"),
    )

    assert [r.node for r in read_ledger(ledger)] == ["implement", "review"]


@pytest.fixture(autouse=True)
def _fresh_notices() -> None:
    forget_told()


def a_record() -> UsageRecord:
    return UsageRecord.model_validate(line())


def test_a_record_lands_in_the_installation_s_state_dir(workspace: Installation) -> None:
    told: list[str] = []

    record_call(a_record(), told.append)

    assert [r.unit for r in read_ledger(workspace.state_dir / "usage-ledger.jsonl")] == [
        "add-marker/1"
    ]
    assert told == []


def test_a_failed_write_is_reported_once_however_many_calls_fail(
    workspace: Installation,
) -> None:
    workspace.state_dir.write_text("not a directory")
    told: list[str] = []

    for _ in range(3):
        record_call(a_record(), told.append)

    assert len(told) == 1


def test_a_record_made_with_no_workspace_loaded_is_dropped_and_reported_once() -> None:
    config.activate(WorkspaceConfig(), None)
    told: list[str] = []

    record_call(a_record(), told.append)
    record_call(a_record(), told.append)

    assert len(told) == 1
    assert "no workspace" in told[0]
