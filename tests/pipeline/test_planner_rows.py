"""The planner's graph call is in the ledger: one `plan` row per `plan_round`, naming the change
planned and no unit (spec: usage-accounting, every agent call writes exactly one row)."""

from __future__ import annotations

import json

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planner import plan_round
from tests.call_rows import Spending, agent_rows
from tests.pipeline.test_planner_runtime import CHANGES, IN_FLIGHT, PLAN


def test_a_plan_round_writes_one_plan_row_naming_the_change_and_no_unit(
    workspace: Installation,
) -> None:
    plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=Spending(answer=json.dumps(PLAN)))

    (row,) = agent_rows(workspace)
    assert (row["node"], row["unit"], row["change"], row["role"]) == (
        "plan",
        "",
        "add-marker",
        "plan",
    )
    assert row["input_tokens"] == 1200
    assert row["cost"]["incremental_usd"] == 0.31
    assert row["outcome"] == "ok"


def test_each_plan_round_is_its_own_row(workspace: Installation) -> None:
    runtime = Spending(answer=json.dumps(PLAN))

    plan_round(changes=CHANGES, in_flight=[], runtime=runtime)
    plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=runtime)

    assert [row["node"] for row in agent_rows(workspace)] == ["plan", "plan"]
