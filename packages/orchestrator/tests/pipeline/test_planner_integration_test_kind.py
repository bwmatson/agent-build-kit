"""A planner reply may give a unit the `integration-test` kind; an unknown kind is refused."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.planner import PlannerError, parse_graph


def reply(kind: str) -> str:
    record = {"id": "feature/1", "change": "feature", "title": "t", "repo": "app", "tier": kind}
    return json.dumps({"units": [record]})


def test_a_unit_of_the_integration_test_kind_parses_to_it() -> None:
    assert parse_graph(reply("integration-test"))[0].tier is TestTier("integration-test")


def test_a_unit_with_an_unknown_kind_is_refused() -> None:
    with pytest.raises(PlannerError, match="integration-test"):
        parse_graph(reply("integration"))
