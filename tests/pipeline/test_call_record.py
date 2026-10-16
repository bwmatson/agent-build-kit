"""One helper writes the ledger row of any agent call, and the unit's steps use it too
(spec: usage-accounting, every agent call writes exactly one row).

The helper is handed the finished `AgentResult`, as a runtime hands it to `on_result`; the
ledger is read back from disk as the report reads it.
"""

from __future__ import annotations

import json

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.call_record import call_recorder, recorded
from agent_build_kit.pipeline.gateway_usage import Spend
from agent_build_kit.pipeline.usage_ledger import (
    LEDGER_NAME,
    UsageRecord,
    forget_told,
    record_call,
)
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.usage import Usage
from tests.redaction_fakes import NAME, SECRET, known
from tests.runtimes.stand_in import StandInRuntime

UNIT = "add-marker/1"
SESSION = "7e1c5a30-2b4d-4f86-a3c9-d0e8b6f21a47"


@pytest.fixture(autouse=True)
def _fresh_notices() -> None:
    forget_told()


def rows(workspace: Installation) -> list[dict]:
    path = workspace.state_dir / LEDGER_NAME
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def finished(**fields) -> AgentResult:
    return AgentResult(ok=True, text="done", **fields)


# --- a call with no unit -----------------------------------------------------------------


def test_a_call_with_no_unit_records_one_row_with_the_reported_figures(
    workspace: Installation,
) -> None:
    record = call_recorder("plan", change="add-marker", repo="app", say=print)

    record(
        finished(
            usage=Usage(
                input_tokens=120,
                output_tokens=40,
                cache_read_input_tokens=900,
                cache_creation_input_tokens=60,
            ),
            cost_usd=0.42,
            turns=3,
            duration_ms=61_000,
            usage_source="reported",
        ),
        role="generic",
        model=None,
        runtime="claude_code",
    )

    (row,) = rows(workspace)
    assert row["kind"] == "agent"
    assert row["node"] == "plan"
    assert row["unit"] == ""
    assert (row["change"], row["repo"], row["tier"]) == ("add-marker", "app", "")
    assert (row["role"], row["model"], row["runtime"]) == ("generic", None, "claude_code")
    assert row["input_tokens"] == 120
    assert row["output_tokens"] == 40
    assert row["cache_read_input_tokens"] == 900
    assert row["cache_creation_input_tokens"] == 60
    assert row["cost"]["incremental_usd"] == pytest.approx(0.42)
    assert row["turns"] == 3
    assert row["duration_ms"] == 61_000
    assert row["usage_source"] == "reported"
    assert row["outcome"] == "ok"


def test_a_failed_result_is_recorded_as_failed_with_its_figures(workspace: Installation) -> None:
    record = call_recorder("plan", change="add-marker", say=print)

    record(
        AgentResult(
            ok=False,
            text="",
            error="claude exited 1",
            usage=Usage(input_tokens=7, output_tokens=3),
            cost_usd=0.05,
            usage_source="reported",
        ),
        role="generic",
        model=None,
        runtime="claude_code",
    )

    (row,) = rows(workspace)
    assert row["outcome"] == "failed"
    assert row["input_tokens"] == 7
    assert row["output_tokens"] == 3
    assert row["cost"]["incremental_usd"] == pytest.approx(0.05)


def test_a_result_with_no_usage_records_absent_figures_and_never_zero(
    workspace: Installation,
) -> None:
    record = call_recorder("plan", say=print)

    record(finished(), role="generic", model=None, runtime="claude_code")

    (row,) = rows(workspace)
    for figure in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        assert row[figure] is None
    assert row["usage_source"] == "none"
    assert (row.get("cost") or {}).get("incremental_usd") is None
    assert row["outcome"] == "ok"


# --- the unit's steps record through the same helper --------------------------------------


def test_a_resumed_calls_cost_is_derived_from_the_sessions_running_total(
    workspace: Installation,
) -> None:
    first = call_recorder("implement", unit=UNIT, change="add-marker", repo="app", say=print)
    resumed = call_recorder(
        "implement", unit=UNIT, change="add-marker", repo="app", resumed=True, say=print
    )

    first(
        finished(session_id=SESSION, cumulative_cost_usd=2.63),
        role="implement",
        model="m",
        runtime="claude_code",
    )
    resumed(
        finished(session_id=SESSION, cumulative_cost_usd=5.49),
        role="implement",
        model="m",
        runtime="claude_code",
    )

    started, continued = rows(workspace)
    assert started["cost"]["incremental_usd"] == pytest.approx(2.63)
    assert started["cost"]["basis"] == "first"
    assert continued["resumed"] is True
    assert continued["cost"]["incremental_usd"] == pytest.approx(2.86)
    assert continued["cost"]["cumulative_usd"] == pytest.approx(5.49)
    assert continued["cost"]["basis"] == "derived"
    assert continued["session_id"] == SESSION


def test_a_gateways_figures_replace_the_agents_and_the_agents_are_kept_beside_them(
    workspace: Installation,
) -> None:
    record = call_recorder("review", unit=UNIT, tier="unit-test", round=2, say=print)

    record(
        finished(
            session_id=SESSION,
            usage=Usage(input_tokens=10, output_tokens=5),
            usage_source="reported",
        ),
        role="review",
        model="m",
        runtime="acp",
        gateway=lambda: Spend(usage=Usage(input_tokens=1000, output_tokens=100), cost_usd=0.5),
    )

    (row,) = rows(workspace)
    assert (row["unit"], row["node"], row["round"], row["tier"]) == (UNIT, "review", 2, "unit-test")
    assert row["usage_source"] == "gateway"
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] == 100
    assert row["reported"]["input_tokens"] == 10
    assert row["cost"]["incremental_usd"] == pytest.approx(0.5)
    assert row["cost"]["basis"] == "reported"


def test_a_session_cost_that_fell_starts_a_new_baseline_and_says_so(
    workspace: Installation,
) -> None:
    said: list[str] = []
    record = call_recorder("fix_checks", unit=UNIT, say=said.append)

    record(
        finished(session_id=SESSION, cumulative_cost_usd=10.0),
        role="implement",
        model="m",
        runtime="claude_code",
    )
    record(
        finished(session_id=SESSION, cumulative_cost_usd=1.2),
        role="implement",
        model="m",
        runtime="claude_code",
    )

    _, second = rows(workspace)
    assert second["cost"]["incremental_usd"] == pytest.approx(1.2)
    assert second["cost"]["cumulative_usd"] == pytest.approx(1.2)
    assert any("reset" in line.lower() for line in said)


# --- the row goes through the ledger's writer ----------------------------------------------


def test_the_row_keeps_its_unit_and_node_as_written_through_the_ledgers_writer(
    workspace: Installation,
) -> None:
    """The helper puts no free text on a row (`outcome` is `ok` or `failed`, every other text
    field identifies), so there is nothing for the writer to withhold."""
    record = call_recorder("restack", unit=UNIT, change="add-marker", say=print)

    record(
        AgentResult(ok=False, text="", error="died"),
        role="generic",
        model=None,
        runtime="claude_code",
    )

    (row,) = rows(workspace)
    assert (row["unit"], row["node"]) == (UNIT, "restack")
    assert row["outcome"] == "failed"


def test_a_secret_in_a_new_nodes_outcome_is_withheld_and_its_unit_and_node_are_kept(
    workspace: Installation,
) -> None:
    forget_told()

    with known():
        record_call(
            UsageRecord(
                at="2026-01-01T10:00:00+00:00",
                unit=UNIT,
                node="restack",
                outcome=f"died: {SECRET}",
            ),
            print,
        )

    written = (workspace.state_dir / LEDGER_NAME).read_text()
    assert SECRET not in written
    (row,) = rows(workspace)
    assert (row["unit"], row["node"]) == (UNIT, "restack")
    assert row["outcome"] == f"died: [redacted:{NAME}]"


# --- a request that records ----------------------------------------------------------------


def test_a_recorded_request_writes_its_row_with_its_own_role_model_and_runtime_after_its_callback(
    workspace: Installation,
) -> None:
    told: list[str] = []
    runtime = StandInRuntime()
    request = AgentRequest(
        prompt="plan it",
        role="generic",
        model="m-1",
        on_result=lambda result: told.append(f"{len(rows(workspace))} rows when called"),
    )

    request = recorded(request, runtime, node="plan", change="add-marker", say=print)
    assert request.on_result is not None
    request.on_result(finished(usage=Usage(input_tokens=5, output_tokens=2)))

    assert told == ["0 rows when called"]
    (row,) = rows(workspace)
    assert (row["node"], row["role"], row["model"], row["runtime"]) == (
        "plan",
        "generic",
        "m-1",
        runtime.name,
    )
    assert row["change"] == "add-marker"
