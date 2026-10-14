"""The checkpoint test helper reports what the library blocks, and nothing it would load."""

from __future__ import annotations

import http

from agent_build_kit.pipeline.units import PLANNED
from tests.checkpoint_types import blocked_in, blocked_on_load


def test_an_enum_off_the_list_is_reported_naming_the_field_and_the_type() -> None:
    update = [("held", "hold_state", PLANNED)]

    assert blocked_on_load(PLANNED) == {("agent_build_kit.pipeline.units", "UnitState")}
    assert blocked_in(update) == ["held.hold_state: agent_build_kit.pipeline.units.UnitState"]


def test_a_standard_library_enum_the_library_does_not_list_is_reported() -> None:
    assert blocked_on_load(http.HTTPStatus.OK) == {("http", "HTTPStatus")}


def test_plain_text_and_the_listed_types_are_not_reported() -> None:
    assert blocked_on_load({"hold_state": "planned", "n": 3}) == set()
