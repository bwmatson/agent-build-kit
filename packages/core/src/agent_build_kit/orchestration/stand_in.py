"""An in-memory `UnitsStore`, for unit tests of callers."""

from __future__ import annotations

import builtins
import copy
from collections.abc import Callable
from typing import Any

from agent_build_kit.orchestration.store import (
    UPDATE_ATTEMPTS,
    StoreConflict,
    StoredUnit,
    UnitNotFound,
    VersionConflict,
)


def _copy(unit: StoredUnit) -> StoredUnit:
    return unit.model_copy(update={"body": copy.deepcopy(unit.body)})


class InMemoryUnitsStore:
    """Holds units and their history in dictionaries."""

    def __init__(self) -> None:
        self._units: dict[str, StoredUnit] = {}
        self._history: dict[str, builtins.list[dict[str, Any]]] = {}

    async def get(self, unit_id: str) -> StoredUnit | None:
        unit = self._units.get(unit_id)
        return None if unit is None else _copy(unit)

    async def list(self) -> builtins.list[StoredUnit]:
        return [_copy(u) for _, u in sorted(self._units.items())]

    async def put_if(
        self, unit_id: str, body: dict[str, Any], version: int, fence: int | None = None
    ) -> StoredUnit:
        stored = self._units.get(unit_id)
        current = 0 if stored is None else stored.version
        if current != version:
            raise VersionConflict(f"{unit_id} is at version {current}, not {version}")
        written = StoredUnit(id=unit_id, body=copy.deepcopy(body), version=version + 1)
        self._units[unit_id] = written
        return _copy(written)

    async def update(
        self,
        unit_id: str,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
        fence: int | None = None,
        attempts: int = UPDATE_ATTEMPTS,
    ) -> StoredUnit:
        for _ in range(attempts):
            stored = await self.get(unit_id)
            body = {} if stored is None else stored.body
            version = 0 if stored is None else stored.version
            new_body = fn(body)
            try:
                return await self.put_if(unit_id, new_body, version, fence)
            except VersionConflict:
                continue
        raise StoreConflict(f"{unit_id} changed on each of {attempts} attempts")

    async def append_history(
        self, unit_id: str, entry: dict[str, Any], fence: int | None = None
    ) -> int:
        if unit_id not in self._units:
            raise UnitNotFound(unit_id)
        entries = self._history.setdefault(unit_id, [])
        entries.append(copy.deepcopy(entry))
        return len(entries)

    async def history(self, unit_id: str) -> builtins.list[dict[str, Any]]:
        return copy.deepcopy(self._history.get(unit_id, []))
