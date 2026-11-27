"""The units store's Alembic migrations: the config for a URL, the head, and where a database is."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATIONS = Path(__file__).parent / "migrations"


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # Alembic's option values are interpolated, so a `%` (an escaped password has them) is doubled.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config("")).get_current_head()
    if head is None:
        raise RuntimeError("the store has no migrations")
    return head


async def current_revision(url: str) -> str | None:
    """The revision the database at `url` is at; None when it has not been migrated."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda held: MigrationContext.configure(held).get_current_revision()
            )
    finally:
        await engine.dispose()
