"""A unit object may carry `needs_less_urgent`, dependency ids to reasons; a malformed one
refuses the plan (spec: planner-priority-edges)."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.planner import PlannerError, parse_plan


def reply(excuse: object) -> str:
    base = {"change": "c", "title": "A unit", "repo": "app", "tier": "unit-test"}
    second = {**base, "id": "c/2", "depends_on": ["c/1"], "needs_less_urgent": excuse}
    return json.dumps({"units": [{**base, "id": "c/1"}, second]})


def refusal(excuse: object) -> str:
    with pytest.raises(PlannerError) as refused:
        parse_plan(reply(excuse))
    return str(refused.value)


@pytest.mark.parametrize("excuse", ["a reason", ["c/1"], 3, None])
def test_a_value_that_is_not_an_object_refuses_the_plan(excuse: object) -> None:
    assert "c/2" in refusal(excuse)


def test_a_key_the_unit_does_not_depend_on_refuses_the_plan() -> None:
    message = refusal({"c/9": "a reason"})

    assert "c/2" in message
    assert "c/9" in message


@pytest.mark.parametrize("reason", ["", "   ", 4, None, ["x"]])
def test_a_blank_or_non_string_reason_refuses_the_plan(reason: object) -> None:
    assert "c/2" in refusal({"c/1": reason})


def test_an_object_of_ids_to_reasons_is_read() -> None:
    # The malformed shape is refused, so the well-formed one beside it is the one read.
    assert "c/2" in refusal({"c/1": "a reason", "c/9": "another"})

    plan = parse_plan(reply({"c/1": "the helper it needs"}))

    assert [unit.id for unit in plan.units] == ["c/1", "c/2"]
