"""The SQL units store on a SQLite file upgraded with Alembic to the head revision.

The conformance suite is the one the in-memory stand-in's tests state. The migrations are run
through Alembic's own API with `sqlalchemy.url` set to the file, as `abk db upgrade` does."""

import importlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect, update

import agent_build_kit.orchestration.sql as sql_package
from agent_build_kit.orchestration.sql.store import SqlUnitsStore
from agent_build_kit.orchestration.sql.tables import UNITS
from tests.support.units_store_conformance import CASES, Harness, run_case

MIGRATIONS = Path(sql_package.__file__).parent / "migrations"


def alembic_config(database: Path) -> Any:
    # Alembic is imported by name: the dependency arrives with the implementation (task 2.2).
    assert MIGRATIONS.is_dir(), "the migrations folder does not exist yet"
    config = importlib.import_module("alembic.config").Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    return config


def upgrade(database: Path) -> None:
    config = alembic_config(database)
    importlib.import_module("alembic.command").upgrade(config, "head")


def table_names(database: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{database}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "units.db"


def test_upgrading_to_head_creates_the_units_and_history_tables(database: Path) -> None:
    upgrade(database)

    assert {"units", "unit_history"} <= table_names(database)


def test_downgrading_to_base_leaves_no_table(database: Path) -> None:
    upgrade(database)
    importlib.import_module("alembic.command").downgrade(alembic_config(database), "base")

    assert table_names(database) <= {"alembic_version"}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_sqlite_store_passes_the_conformance_case(case: str, database: Path) -> None:
    def factory() -> Harness:
        upgrade(database)
        sync = create_engine(f"sqlite:///{database}")

        def write_behind(unit_id: str, body: dict[str, Any], version: int) -> None:
            with sync.begin() as connection:
                connection.execute(
                    update(UNITS)
                    .where(UNITS.c.id == unit_id)
                    .values(body=body, version=version + 1)
                )

        # Imported here: the async extras (greenlet) arrive with the implementation (task 2.2).
        asyncio_ext = importlib.import_module("sqlalchemy.ext.asyncio")
        engine = asyncio_ext.create_async_engine(f"sqlite+aiosqlite:///{database}")
        return Harness(store=SqlUnitsStore(engine), write_behind=write_behind)

    run_case(case, factory)
