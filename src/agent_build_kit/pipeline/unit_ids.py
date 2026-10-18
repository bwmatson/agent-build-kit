"""The id of a planned unit comes from the groups it carries, not from the planner."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence

from agent_build_kit.pipeline.unit_store import UNPLANNED, StoredUnit
from agent_build_kit.pipeline.units import PLANNED, Unit, UnitState

_LEADING_NUMBER = re.compile(r"\d+")


def is_reusable(stored: StoredUnit, retired: Collection[str] = ()) -> bool:
    """Whether a plan may rewrite or revive `stored` in place: not started, not retired."""
    return (
        stored.state in (PLANNED, UNPLANNED)
        and not stored.has_work
        and stored.state != UnitState.RETIRED
        and stored.id not in retired
    )


def taken_ids(stored: Sequence[StoredUnit], retired: Collection[str] = ()) -> set[str]:
    """The ids no label may stand for: those of retired, started and finished units."""
    return {unit.id for unit in stored if not is_reusable(unit, retired)} | set(retired)


def _number(unit_id: str) -> int:
    found = _LEADING_NUMBER.match(unit_id.rsplit("/", 1)[-1])
    return int(found.group()) if found else 0


def assign_unit_ids(
    units: Sequence[Unit],
    *,
    stored: Sequence[StoredUnit],
    retired: Collection[str],
    highest_group: int,
) -> tuple[Unit, ...]:
    """`units` with each id assigned from its groups, and every `depends_on` label rewritten.

    A unit of change `c` is `c/<lowest group of c it carries>`; it keeps the id of an
    unstarted stored unit of `c` with exactly its groups; and when the rule's id is taken it
    gets the smallest free integer above every number the change has used.
    """
    reusable = {u.id: u for u in stored if is_reusable(u, retired)}
    known = {u.id for u in stored} | set(retired)
    ids: dict[int, str] = {i: u.id for i, u in enumerate(units) if not u.groups}
    order = sorted((i for i, u in enumerate(units) if u.groups), key=lambda i: min(units[i].groups))

    def free(candidate: str) -> bool:
        return candidate not in ids.values() and (candidate not in known or candidate in reusable)

    for i in order:
        owned = sorted(
            (_number(s.id), s.id)
            for s in reusable.values()
            if s.change == units[i].change
            and set(s.groups) == set(units[i].groups)
            and s.id not in ids.values()
        )
        if owned:
            ids[i] = owned[0][1]
    for i in order:
        if i in ids:
            continue
        change = units[i].change
        candidate = f"{change}/{min(units[i].groups)}"
        if not free(candidate):
            used = [_number(s.id) for s in stored if s.change == change]
            number = max([highest_group, *used]) + 1
            while not free(f"{change}/{number}"):
                number += 1
            candidate = f"{change}/{number}"
        ids[i] = candidate

    by_label = {u.id: ids[i] for i, u in enumerate(units)}
    return tuple(
        u.model_copy(
            update={
                "id": ids[i],
                "depends_on": tuple(dict.fromkeys(by_label.get(d, d) for d in u.depends_on)),
            }
        )
        for i, u in enumerate(units)
    )
