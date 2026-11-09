"""A lane run's agent calls write the rows a worker's would: the resolver and the port are
`restack` rows for the unit, its change and its repository, each asked of the guard first, and the
review writes the rows of a worker's review with the review model (spec: restack-conflicts, a
review in the lane).

The scene is `tests/lane_run_usage_support.py`'s, over the usage ledger the pipeline writes.
"""

from __future__ import annotations

from agent_build_kit.pipeline.usage_ledger import UsageRecord, read_ledger
from tests.lane_run_usage_support import Lane, make_lane  # noqa: F401 — fixture


def rows_of(lane: Lane, node: str) -> list[UsageRecord]:
    ledger = lane.graph.inst.state_dir / "usage-ledger.jsonl"
    return [row for row in read_ledger(ledger) if row.node == node]
