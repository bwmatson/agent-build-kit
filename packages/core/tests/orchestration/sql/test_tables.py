"""The units store's schema, its Alembic migrations, and the SQL store on a migrated SQLite file.

The conformance suite is the one the in-memory stand-in's tests state. The migrations are run
through Alembic's own API with `sqlalchemy.url` set to the file, as `abk db upgrade` does. The
store's cases live here, not in a `test_store.py`: a test file base name is unique across the
repository and the orchestrator's notify store already holds that one."""

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, update
from sqlalchemy.ext.asyncio import create_async_engine

import agent_build_kit.orchestration.sql as sql_package
from agent_build_kit.orchestration.sql.store import SqlUnitsStore
from agent_build_kit.orchestration.sql.tables import METADATA, UNITS
from tests.support.units_store_conformance import CASES, Harness, run_case

MIGRATIONS = Path(sql_package.__file__).parent / "migrations"


def alembic_config(database: Path | None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    if database is not None:
        config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def upgrade(database: Path) -> None:
    command.upgrade(alembic_config(database), "head")


def table_names(database: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{database}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "units.db"


def test_the_schema_creates_the_units_and_history_tables_with_their_keys() -> None:
    engine = create_engine("sqlite://")
    METADATA.create_all(engine)
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) == {"units", "unit_history"}
    assert inspector.get_pk_constraint("units")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("unit_history")["constrained_columns"] == [
        "unit_id",
        "sequence",
    ]
    foreign = inspector.get_foreign_keys("unit_history")[0]
    assert (foreign["referred_table"], foreign["referred_columns"]) == ("units", ["id"])


def test_upgrading_to_head_creates_the_units_and_history_tables(database: Path) -> None:
    upgrade(database)

    assert {"units", "unit_history"} <= table_names(database)


def test_the_migrated_schema_matches_the_tables(database: Path) -> None:
    upgrade(database)
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection), METADATA)
    finally:
        engine.dispose()

    assert differences == []


def test_upgrading_on_a_connection_the_caller_holds_needs_no_url(database: Path) -> None:
    config = alembic_config(None)
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()

    assert {"units", "unit_history"} <= table_names(database)


def test_downgrading_to_base_leaves_no_table(database: Path) -> None:
    upgrade(database)
    command.downgrade(alembic_config(database), "base")

    assert table_names(database) <= {"alembic_version"}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_sqlite_store_passes_the_conformance_case(case: str, database: Path) -> None:
    def factory() -> Harness:
        upgrade(database)
        sync = create_engine(f"sqlite:///{database}")
        engine = create_async_engine(f"sqlite+aiosqlite:///{database}")

        def write_behind(unit_id: str, body: dict[str, Any], version: int) -> None:
            with sync.begin() as connection:
                connection.execute(
                    update(UNITS)
                    .where(UNITS.c.id == unit_id)
                    .values(body=body, version=version + 1)
                )

        async def close() -> None:
            await engine.dispose()
            sync.dispose()

        return Harness(store=SqlUnitsStore(engine), write_behind=write_behind, close=close)

    run_case(case, factory)
