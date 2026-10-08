"""What the `abk serve` tests share: a pipeline in each state, a thread in the
checkpoint store, and a snapshot of every file the server must leave alone."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node, UnitRun
from agent_build_kit.graph.unit import seed_thread
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    RUNNING,
    SATISFIED,
)
from tests.factories import unit

# id -> (effective state, cause, held_by, note) as the pipeline below leaves them.
EXPECTED: dict[str, tuple[str, str | None, str, str]] = {
    "feature/1": ("merged", "merged", "", "merged"),
    "feature/2": ("in_review", None, "", ""),
    "feature/3": ("blocked", None, "", ""),
    "feature/4": ("planned", None, "", ""),
    "feature/5": ("held", "review_escalated_class", "review", "escalated: a class of bug"),
    "feature/6": ("failed", "failed", "", "tier 1 failed"),
    "feature/7": ("running", None, "", ""),
    "feature/8": ("satisfied", None, "", ""),
    "feature/9": ("closed", "closed", "", "closed unmerged"),
}


def seed_pipeline(installation: Installation) -> UnitStore:
    """Nine `feature` units, one in each state the page tells apart. Number 3 is
    gated on number 2 merging, and 4 is stacked on 2."""
    store = UnitStore(installation.state_dir / "units.json")
    store.upsert(
        [
            unit("feature/1", change="feature", title="Base"),
            unit("feature/2", change="feature", title="Middle", depends_on=("feature/1",)),
            unit(
                "feature/3",
                change="feature",
                title="Gated",
                repo="platform",
                depends_on=("feature/2",),
                merge_before=("feature/2",),
            ),
            unit("feature/4", change="feature", title="Stacked", depends_on=("feature/2",)),
            unit("feature/5", change="feature", title="Held"),
            unit("feature/6", change="feature", title="Failed"),
            unit("feature/7", change="feature", title="Running"),
            unit("feature/8", change="feature", title="Satisfied"),
            unit("feature/9", change="feature", title="Closed"),
        ]
    )
    store.set_state("feature/1", MERGED, pr=11, branch="spec/feature/1", cause=Cause.MERGED)
    store.set_state("feature/1", MERGED, note="merged", cause=Cause.MERGED)
    store.set_state("feature/2", RUNNING, branch="spec/feature/2")
    store.set_state("feature/2", IN_REVIEW, pr=12)
    store.set_state(
        "feature/5",
        HELD,
        note="escalated: a class of bug",
        held_by=HeldBy.REVIEW,
        cause=Cause.REVIEW_ESCALATED_CLASS,
    )
    store.set_state("feature/6", FAILED, note="tier 1 failed", cause=Cause.FAILED)
    store.set_state("feature/7", RUNNING, branch="spec/feature/7")
    store.set_state("feature/8", SATISFIED)
    store.set_state("feature/9", CLOSED, note="closed unmerged", cause=Cause.CLOSED)
    return store


def seed_review_round(installation: Installation, unit_id: str, review_round: int) -> None:
    """A thread for `unit_id` in the real checkpoint store, waiting in review."""
    change = unit_id.split("/")[0]
    state = UnitRun(unit_id=unit_id, change=change, review_round=review_round)

    async def write() -> None:
        async with open_checkpointer(unit_graphs_path(installation.state_dir)) as saver:
            await seed_thread(saver, state, as_node=Node.AWAIT_REVIEW)

    asyncio.run(write())


def snapshot(directory: Path) -> dict[str, bytes]:
    """Every file under `directory` and its bytes, apart from the SQLite shared-memory
    index, which opening a database may create without changing what it holds."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and not path.name.endswith("-shm")
    }
