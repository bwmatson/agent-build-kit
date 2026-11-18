"""The hold helpers live in `pipeline.holds`; `pipeline.events` shares those objects."""

import importlib
from types import ModuleType

import pytest

HOLD_NAMES = [
    "held_cause",
    "held_for_its_own_reason",
    "restore_depth_hold",
    "takeover_note",
    "OWED_STATES",
    "OWED_CAUSES",
    "MOVED_BASE_CAUSES",
    "Claim",
    "hold_for_conflict",
    "in_a_lane_run",
    "read_base_tip",
]


def load(module: str) -> ModuleType:
    return importlib.import_module(f"agent_build_kit.pipeline.{module}")


@pytest.mark.parametrize("name", HOLD_NAMES)
def test_the_events_module_shares_the_holds_module_object_for_the_name(name: str) -> None:
    holds = load("holds")
    events = load("events")

    assert getattr(events, name) is getattr(holds, name)
