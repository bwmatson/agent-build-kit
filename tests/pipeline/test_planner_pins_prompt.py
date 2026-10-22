"""A split request gives the planner the held unit's groups in order, the pins, the two tiers and
their ceilings, the piece ids, and the retired ids (spec: split-planning)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.planner import build_prompt, in_flight_item
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.verdict import ReviewTier, SplitRequest
from tests.calibration_support import limits
from tests.factories import stored_unit
from tests.prompt_text import flat
from tests.tier_ceiling_support import GROUPS, configure

TASKS = "".join(
    f"## {n}. [app] [unit-test] Group {n}\n\n- [ ] {n}.1 Test: it.\n\n" for n in (1, 2, 3)
)
HELD = stored_unit("c/1", change="c", groups=(1, 2, 3), depends_on=("c/0",))
DRIVEN = SplitRequest(
    earned=ReviewTier.FULL, planned=ReviewTier.AUTO, lines=900, ceiling=750, drivers=(2,)
)


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    limits()
    configure(enabled=True)


def asked(split: SplitRequest) -> str:
    """The block of the instructions that speaks of the pieces, squeezed and lower-cased."""
    retired = stored_unit("c/9", change="c", state=UnitState.RETIRED, branch="spec/c/9")
    prompt = build_prompt(
        {"c": TASKS},
        [in_flight_item(retired, [retired])],
        groups=GROUPS,
        split=split,
        held=HELD,
    )
    return flat(next(block for block in prompt.split("\n\n") if "c/1-s1" in block)).lower()


def test_the_instructions_name_the_groups_in_order_the_pin_and_both_tiers_with_ceilings() -> None:
    block = asked(DRIVEN)

    assert "1, 2, 3" in block
    assert "pin" in block and "group 2" in block
    for tier, ceiling in (("full", "750"), ("auto", "5000")):
        assert tier in block and ceiling in block


def test_the_instructions_give_the_piece_ids_say_to_chain_keep_the_order_and_list_retired() -> None:
    block = asked(DRIVEN)

    assert "c/1-s1" in block and "c/1-s2" in block
    assert "chain" in block and "depend" in block
    assert "order" in block
    assert "c/9" in block


def test_with_no_drivers_they_give_the_ceiling_and_ask_only_that_each_unit_come_under_it() -> None:
    block = asked(
        SplitRequest(earned=ReviewTier.FULL, planned=ReviewTier.FULL, lines=900, ceiling=750)
    )

    assert "750" in block and "ceiling" in block and "under" in block
    assert "pin" not in block
