"""The units store: the Protocol every implementation of the unit table satisfies.

A unit is a JSON body under an id with a version. `put_if` writes only when the stored version
equals the one given; `update` is a compare-and-swap retry loop over it. History entries are
appended per unit and keep their order.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, Protocol

from agent_build_kit.model import Frozen

# How many times `update` tries before it raises `StoreConflict`.
UPDATE_ATTEMPTS = 5


class StoreConflict(Exception):
    """A write that could not be made because the stored unit kept changing."""


class VersionConflict(StoreConflict):
    """`put_if` was given a version that is not the stored one."""


class UnitNotFound(Exception):
    """`update` or `append_history` named a unit that is not stored."""


class StoredUnit(Frozen):
    """A unit as stored: its id, JSON body and version."""

    id: str
    body: dict[str, Any]
    version: int


class UnitsStore(Protocol):
    """The units table's operations. `fence` is accepted and ignored until leases add tokens."""

    async def get(self, unit_id: str) -> StoredUnit | None:
        """The unit stored under `unit_id`, or None."""
        ...

    async def list(self) -> builtins.list[StoredUnit]:
        """Every stored unit, ordered by id."""
        ...

    async def put_if(
        self, unit_id: str, body: dict[str, Any], version: int, fence: int | None = None
    ) -> StoredUnit:
        """Write `body` when the stored version is `version` (0 for a unit not yet stored);
        return it at version + 1, or raise `VersionConflict`."""
        ...

    async def update(
        self,
        unit_id: str,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
        fence: int | None = None,
        attempts: int = UPDATE_ATTEMPTS,
    ) -> StoredUnit:
        """Apply `fn` to the stored body and write the result, retrying against a concurrent
        change up to `attempts` times, then raise `StoreConflict`. Raises `UnitNotFound` when the
        unit is not stored: `put_if` at version 0 is what creates one."""
        ...

    async def append_history(
        self, unit_id: str, entry: dict[str, Any], fence: int | None = None
    ) -> int:
        """Append `entry` to the unit's history; return its sequence number, from 1. Raises
        `UnitNotFound` when the unit is not stored, as history belongs to a stored unit."""
        ...

    async def history(self, unit_id: str) -> builtins.list[dict[str, Any]]:
        """The unit's history entries in the order they were appended."""
        ...
