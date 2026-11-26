"""The units store over SQLAlchemy Core and an async engine."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent_build_kit.orchestration.store import UPDATE_ATTEMPTS, StoredUnit

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


class SqlUnitsStore:
    """A `UnitsStore` whose units and history live in the tables of `tables.py`."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, unit_id: str) -> StoredUnit | None:
        raise NotImplementedError

    async def list(self) -> builtins.list[StoredUnit]:
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
