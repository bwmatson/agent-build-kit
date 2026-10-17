"""A lane run's agent calls write the rows a worker's would: the resolver and the port are
`restack` rows for the unit, its change and its repository, each asked of the guard first, and the
review writes the rows of a worker's review with the review model (spec: restack-conflicts, a
review in the lane).

The scene is `tests/lane_run_usage_support.py`'s, over the usage ledger the pipeline writes.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit.pipeline.usage_ledger import UsageRecord, read_ledger
from tests.graph.agent_fakes import MODELS
from tests.lane_run_usage_support import Lane, make_lane  # noqa: F401 — fixture
from tests.tick_driver import OTHER


def rows_of(lane: Lane, node: str) -> list[UsageRecord]:
    ledger = lane.graph.inst.state_dir / "usage-ledger.jsonl"
    return [row for row in read_ledger(ledger) if row.node == node]


def test_the_resolver_and_the_port_write_restack_rows_for_the_unit_each_asked_of_the_guard(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
) -> None:
    lane = make_lane()
    lane.open()

    lane.scene.lane_moves()

    stored = lane.graph.store.get(OTHER)
    whose = {(OTHER, stored.change, stored.repo)}
    resolver = rows_of(lane, "restack")
    assert len(resolver) == 2, "the resolver's two calls"
    assert {(row.unit, row.change, row.repo) for row in resolver} == whose
    assert {(row.unit, row.change, row.repo) for row in rows_of(lane, "adapt")} == whose
    assert len(lane.decisions) == len(lane.runtime.requests), "each call asked of the guard first"


def test_the_review_in_the_lane_writes_a_worker_reviews_rows_with_the_review_model(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
) -> None:
    lane = make_lane()
    lane.open()

    lane.scene.lane_moves()

    (review,) = rows_of(lane, "review")
    # The node's own model, as in a worker: a review of a ported result is a re-review.
    assert (review.unit, review.model) == (OTHER, MODELS.rework_review)
    assert len(lane.decisions) == len(lane.runtime.requests)
