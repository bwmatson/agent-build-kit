"""A unit waiting on the fix of a product defect goes on once that fix is in review, whether it
is parked planned and gated or failed; a unit of the fix change itself keeps the usual rule
(spec: e2e-group-scope)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.unit_store import RequeueReason
from agent_build_kit.pipeline.units import FAILED, PLANNED, EdgeKind, edge_kind
from tests.factories import stored_unit
from tests.product_defect_fakes import FIX


def waiter(state: str, **fields: object):
    return stored_unit("kid/1", change="kid", state=state, **fields)


@pytest.mark.parametrize(
    "child",
    [waiter(PLANNED, gated_requeue=RequeueReason.RESUME), waiter(FAILED)],
    ids=["gated", "failed"],
)
def test_a_waiter_on_a_product_defect_fix_has_a_review_edge(child) -> None:
    fix = stored_unit(f"{FIX}/1", change=FIX)

    assert edge_kind(child, fix, {}).kind is EdgeKind.REVIEW


@pytest.mark.parametrize("state", [PLANNED, FAILED])
def test_a_unit_of_the_fix_change_itself_keeps_the_merge_edge(state: str) -> None:
    child = stored_unit(f"{FIX}/2", change=FIX, state=state, gated_requeue=RequeueReason.RESUME)
    earlier = stored_unit(f"{FIX}/1", change=FIX)

    assert edge_kind(child, earlier, {}).kind is EdgeKind.MERGE
