"""An in-memory `UnitsStore`, for unit tests of callers."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any

from agent_build_kit.orchestration.store import UPDATE_ATTEMPTS, StoredUnit


class InMemoryUnitsStore:
    """Holds units and their history in dictionaries."""

    async def get(self, unit_id: str) -> StoredUnit | None:
        raise NotImplementedError

    async def list(self) -> list[StoredUnit]:
        raise NotImplementedError

    async def put_if(
        self, unit_id: str, body: dict[str, Any], version: int, fence: int | None = None
    ) -> StoredUnit:
        raise NotImplementedError

    async def update(
        self,
        unit_id: str,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
        fence: int | None = None,
        attempts: int = UPDATE_ATTEMPTS,
    ) -> StoredUnit:
        raise NotImplementedError

    async def append_history(
        self, unit_id: str, entry: dict[str, Any], fence: int | None = None
    ) -> int:
        raise NotImplementedError

    async def history(self, unit_id: str) -> builtins.list[dict[str, Any]]:
        raise NotImplementedError
