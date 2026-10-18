"""The id of a planned unit comes from the groups it carries, not from the planner."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Unit


def assign_unit_ids(
    units: Sequence[Unit],
    *,
    stored: Sequence[StoredUnit],
    retired: Collection[str],
    highest_group: int,
) -> tuple[Unit, ...]:
    """`units` with each id assigned from its groups, and every `depends_on` label rewritten."""
    raise NotImplementedError
