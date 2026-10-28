"""A ledger row records the model the runtime reported beside the model asked for, an old row
reads without it, and the usage forecast groups a call with no model by the reported one
(spec: planner-model, the ledger records the model that ran)."""

from __future__ import annotations

import json

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.call_record import call_recorder
from agent_build_kit.pipeline.usage_forecast_history import tier_cells
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, read_ledger
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.runtimes import AgentResult
from tests.usage_forecast_fixtures import Fixture

REPORTED = "claude-sonnet-5-5"


def rows(workspace: Installation) -> list[dict]:
    path = workspace.state_dir / LEDGER_NAME
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_call_with_no_model_records_the_model_the_runtime_reported(
    workspace: Installation,
) -> None:
    record = call_recorder("plan", change="add-marker", say=print)

    record(
        AgentResult(ok=True, text="done", reported_model=REPORTED),
        role="generic",
        model=None,
        runtime="claude_code",
    )

    (row,) = rows(workspace)
    assert row["model"] is None
    assert row["reported_model"] == REPORTED


def test_a_call_with_a_model_records_both(workspace: Installation) -> None:
    record = call_recorder("plan", change="add-marker", say=print)

    record(
        AgentResult(ok=True, text="done", reported_model="claude-opus-5-5"),
        role="generic",
        model="opus",
        runtime="claude_code",
    )

    (row,) = rows(workspace)
    assert (row["model"], row["reported_model"]) == ("opus", "claude-opus-5-5")


def test_a_row_written_before_the_field_reads_with_it_absent(workspace: Installation) -> None:
    path = workspace.state_dir / LEDGER_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {"kind": "agent", "at": "2026-01-01T10:00:00+00:00", "unit": "", "node": "plan"}
    path.write_text(json.dumps(old | {"model": None}) + "\n")

    call_recorder("plan", say=print)(
        AgentResult(ok=True, text="done", reported_model=REPORTED),
        role="generic",
        model=None,
        runtime="claude_code",
    )

    old_row, new_row = read_ledger(path)

    assert old_row.reported_model is None
    assert new_row.reported_model == REPORTED


def test_the_forecast_groups_a_call_with_no_model_by_its_reported_model() -> None:
    fixture = Fixture()
    fixture.units(10, ReviewTier.AUTO, [("review", 1, 1.0)])
    # Half the units ran the same model without asking for it by name.
    fixture.records[5:] = [
        r.model_copy(update={"model": None, "reported_model": "model-a"})
        for r in fixture.records[5:]
    ]

    found = tier_cells(
        fixture.records,
        fixture.verdicts,
        tier=ReviewTier.AUTO,
        estimated_lines=10,
        points_per_usd=2.5,
        min_runs=10,
        quantile=0.5,
    )

    (cell,) = found.cells
    assert cell.cell.model == "model-a"
    assert cell.chance == 1.0
