"""The state a checkpoint test builds from node updates is built through validation, so the
serializer has nothing to warn about, and the guard can still see a list in a tuple field.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from agent_build_kit.graph.state import UnitRun
from agent_build_kit.pipeline.unit_store import Cause
from tests.checkpoint_types import blocked_on_load, node_updates, state_from_updates
from tests.graph.test_checkpoint_allowlist import populated
from tests.graph.test_held_state_plain_text import HOLD_IDS, HOLDS, THREAD, held_unit
from tests.graph.test_hold_causes import Held

SERIALIZER_WARNING = "PydanticSerializationUnexpectedValue"


def serializer_warnings(state: UnitRun) -> list[str]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        blocked_on_load(state)
    return [str(w.message) for w in caught if SERIALIZER_WARNING in str(w.message)]


@pytest.mark.parametrize("hold", HOLDS, ids=HOLD_IDS)
def test_the_state_a_held_unit_wrote_serialises_without_a_warning(
    tmp_path: Path, hold: Held
) -> None:
    updates = node_updates(held_unit(tmp_path, hold), THREAD)

    state = state_from_updates(updates)

    assert serializer_warnings(state) == []


def test_a_list_in_a_tuple_field_is_seen_unless_the_state_is_validated() -> None:
    copied = populated(UnitRun).model_copy(update={"groups": [1]})
    validated = state_from_updates([("__start__", "groups", [1])])

    assert serializer_warnings(copied) != []
    assert serializer_warnings(validated) == []
    assert validated.groups == (1,)


def test_a_node_update_holding_an_off_list_enum_is_still_blocked() -> None:
    state = state_from_updates([("node", "last_findings", [{"cause": Cause.BASE_CHANGED}])])

    assert blocked_on_load(state) != set()
