"""The units store over SQLAlchemy Core and an async engine."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from agent_build_kit.orchestration.sql.tables import UNIT_HISTORY, UNITS
from agent_build_kit.orchestration.store import (
    UPDATE_ATTEMPTS,
    StoreConflict,
    StoredUnit,
    UnitNotFound,
    VersionConflict,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

# How many times `append_history` retries a sequence number another writer took first.
HISTORY_ATTEMPTS = 20


class SqlUnitsStore:
    """A `UnitsStore` whose units and history live in the tables of `tables.py`."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, unit_id: str) -> StoredUnit | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(UNITS.c.id, UNITS.c.body, UNITS.c.version).where(UNITS.c.id == unit_id)
                )
            ).first()
        if row is None:
            return None
        return StoredUnit(id=row[0], body=row[1], version=row[2])

    async def list(self) -> builtins.list[StoredUnit]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(UNITS.c.id, UNITS.c.body, UNITS.c.version).order_by(UNITS.c.id)
                )
            ).all()
        return [StoredUnit(id=r[0], body=r[1], version=r[2]) for r in rows]

    async def put_if(
        self, unit_id: str, body: dict[str, Any], version: int, fence: int | None = None
    ) -> StoredUnit:
        now = datetime.now(UTC)
        async with self._engine.begin() as connection:
            if version == 0:
                try:
                    await connection.execute(
                        insert(UNITS).values(id=unit_id, body=body, version=1, updated_at=now)
                    )
                except IntegrityError as error:
                    raise VersionConflict(unit_id) from error
            else:
                result = await connection.execute(
                    update(UNITS)
                    .where(UNITS.c.id == unit_id, UNITS.c.version == version)
                    .values(body=body, version=version + 1, updated_at=now)
                )
                if result.rowcount != 1:
                    raise VersionConflict(unit_id)
        return StoredUnit(id=unit_id, body=body, version=version + 1)

    async def update(
        self,
        unit_id: str,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
        fence: int | None = None,
        attempts: int = UPDATE_ATTEMPTS,
    ) -> StoredUnit:
        for _ in range(attempts):
            current = await self.get(unit_id)
            if current is None:
                raise UnitNotFound(unit_id)
            try:
                return await self.put_if(unit_id, fn(current.body), current.version, fence)
            except VersionConflict:
                continue
        raise StoreConflict(f"{unit_id} kept changing across {attempts} attempts")

    async def append_history(
        self, unit_id: str, entry: dict[str, Any], fence: int | None = None
    ) -> int:
        for _ in range(HISTORY_ATTEMPTS):
            try:
                async with self._engine.begin() as connection:
                    exists = (
                        await connection.execute(select(UNITS.c.id).where(UNITS.c.id == unit_id))
                    ).first()
                    if exists is None:
                        raise UnitNotFound(unit_id)
                    last = (
                        await connection.execute(
                            select(func.max(UNIT_HISTORY.c.sequence)).where(
                                UNIT_HISTORY.c.unit_id == unit_id
                            )
                        )
                    ).scalar()
                    sequence = (last or 0) + 1
                    await connection.execute(
                        insert(UNIT_HISTORY).values(unit_id=unit_id, sequence=sequence, entry=entry)
                    )
                return sequence
            except IntegrityError:
                continue  # another writer took the sequence, or the unit vanished: look again
        raise StoreConflict(f"{unit_id} history kept changing across {HISTORY_ATTEMPTS} attempts")

    async def history(self, unit_id: str) -> builtins.list[dict[str, Any]]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(UNIT_HISTORY.c.entry)
                    .where(UNIT_HISTORY.c.unit_id == unit_id)
                    .order_by(UNIT_HISTORY.c.sequence)
                )
            ).all()
        return [r[0] for r in rows]
