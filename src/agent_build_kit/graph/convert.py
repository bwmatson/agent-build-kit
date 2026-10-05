"""Moving the units in flight onto threads (docs/unit-graph.md, Moving the units in flight)."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_build_kit.graph.state import Node, UnitRun
from agent_build_kit.graph.unit import seed_thread, thread_position
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, RUNNING

# The steps the engine before the switch recorded in a unit's `resume_from`.
TESTS = "tests"
IMPLEMENT = "implement"
REVIEW = "review"
# A review of a rework, which has its own model.
REWORK_REVIEW = "rework_review"
VERIFY = "verify"

# The node whose finishing leaves a thread about to run the node a stored step
# names (None: before the first node), and the state its router chooses on.
Seed = tuple[Node | None, dict[str, Any]]


def _seed(stored: StoredUnit) -> Seed | None:
    """Where `stored`'s thread starts, or None when nothing is in flight."""
    tier2 = stored.tier == "tier2"
    step = stored.resume_from
    if stored.state == IN_REVIEW:
        return Node.OPEN_PR, {"status": RunStatus.OPEN, "pr": stored.pr}
    if stored.state == HELD:
        held = {"held": "held", "status": RunStatus.HELD, "detail": "held before the switch"}
        return Node.PUSH, held
    if step in (REVIEW, REWORK_REVIEW):
        reworking = step == REWORK_REVIEW
        return Node.CHECKS, {"checks_ok": True, "had_feedback": reworking, "tier2": tier2}
    if step == VERIFY:
        # The engine before the switch recorded VERIFY before tier 2 ran, so a tier 2 unit
        # has not passed it: `after_prepare` picks `tier2` or `verify_base`.
        return Node.PREPARE, {"base_commits": 1, "head_approved": True, "tier2": tier2}
    if stored.feedback:
        return Node.PREPARE, {"had_feedback": True, "base_commits": 1, "tier2": tier2}
    if step == TESTS:
        return Node.PREPARE, {"base_commits": 0, "tier2": tier2}
    if step == IMPLEMENT:
        return Node.TESTS, {"tier2": tier2}
    # A restack, a step this version does not know, or a run killed before it
    # recorded any step: start again from prepare, which looks at the branch.
    return (None, {}) if step or stored.state == RUNNING else None


async def convert_units_in_flight(saver: BaseCheckpointSaver, store: UnitStore) -> tuple[str, ...]:
    """Seed a thread for each stored unit that has no thread and something in
    flight, positioned at the node its stored step names; return their ids.

    Runs on every tick but only seeds a unit without a thread, so once the
    stores the previous engine left are converted it finds nothing to do. The
    stored step and in-run progress are cleared as they are read: nothing else
    reads them."""
    seeded: list[str] = []
    for stored in store.all():
        seed = _seed(stored)
        if seed is not None and (await thread_position(saver, stored.id)).state is None:
            node, values = seed
            # What the run had in hand moves with it: the thread is where it lives now.
            run = UnitRun(
                unit_id=stored.id,
                change=stored.change,
                groups=stored.groups,
                **{**stored.classic_run, **values},
            )
            await seed_thread(saver, run, as_node=node)
            seeded.append(stored.id)
        if stored.resume_from or stored.classic_run:
            store.clear_converted(stored.id)
    return tuple(seeded)
