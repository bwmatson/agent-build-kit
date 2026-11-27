"""The Checkpoints interface: one conformance suite that takes an implementation.

The suite runs here against the local implementation; the local-only cases pin that the saver
opens the installation's unit graphs file, carries an older database over, and resumes a thread
the saver checkpointed before the interface existed.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.engine import make_url

from agent_build_kit import orchestration
from agent_build_kit.graph.build import compile_graph
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.run import run_thread
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.checkpoints import INTERFACE, Checkpoints
from agent_build_kit.orchestration.local.checkpoints import LocalCheckpoints
from agent_build_kit.orchestration.sql.checkpoints import open_postgres_checkpointer, psycopg_url
from agent_build_kit.run_support import thread_of
from tests.conftest import make_installation
from tests.graph.checkpoint_reads import a_config
from tests.graph.test_checkpoint_allowlist import Unlisted, populated
from tests.tracked_files import guarded_files, source_tree_folders, source_trees


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    orchestration.reset()
    yield
    orchestration.reset()


@pytest.fixture
def local_installation(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path / "planning",
        deployment=dict(kind="local"),
        planning=dict(local_dir=str(tmp_path / "local"), state_dir=str(tmp_path / "state")),
    )


# The connection string of a PostgreSQL database; the `azurite` cases skip without it.
POSTGRES_SETTING = "ABK_TEST_POSTGRES_CONNECTION_STRING"


class StoreCheckpoints:
    """The store's PostgreSQL saver, opened over one URL, as the Checkpoints interface."""

    def __init__(self, url: str) -> None:
        self.url = url

    def open(self) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
        return open_postgres_checkpointer(self.url)


@pytest.fixture
def postgres_store_checkpoints() -> Iterator[Checkpoints]:
    """The store's saver over a schema of its own in the database named by the setting."""
    dsn = os.environ.get(POSTGRES_SETTING)
    if not dsn:
        pytest.skip(f"{POSTGRES_SETTING} is not set: no PostgreSQL database to run against")
    psycopg = pytest.importorskip("psycopg")
    schema = f"checkpoints_{uuid.uuid4().hex}"
    url = (
        make_url(dsn)
        .set(drivername="postgresql+asyncpg", query={"options": f"-c search_path={schema}"})
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
        try:
            yield StoreCheckpoints(url)
        finally:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture(params=["local", pytest.param("postgres", marks=pytest.mark.azurite)])
def checkpoints(request: pytest.FixtureRequest, local_installation: Installation) -> Checkpoints:
    if request.param == "postgres":
        return request.getfixturevalue("postgres_store_checkpoints")
    return orchestration.get(INTERFACE, local_installation)


def test_a_checkpoint_written_is_read_back(checkpoints: Checkpoints) -> None:
    checkpoint = empty_checkpoint()

    async def run() -> Any:
        async with checkpoints.open() as saver:
            await saver.aput(a_config("feature/1"), checkpoint, {"source": "input", "step": 0}, {})
            return await saver.aget_tuple(a_config("feature/1"))

    found = asyncio.run(run())

    assert found is not None
    assert found.checkpoint["id"] == checkpoint["id"]


def test_a_threads_checkpoints_are_listed_newest_first(checkpoints: Checkpoints) -> None:
    first, second = empty_checkpoint(), empty_checkpoint()

    async def run() -> list[str]:
        async with checkpoints.open() as saver:
            config = await saver.aput(
                a_config("feature/1"), first, {"source": "input", "step": 0}, {}
            )
            await saver.aput(config, second, {"source": "loop", "step": 1}, {})
            await saver.aput(a_config("feature/2"), empty_checkpoint(), {}, {})
            return [c.checkpoint["id"] async for c in saver.alist(a_config("feature/1"))]

    assert asyncio.run(run()) == [second["id"], first["id"]]


def test_a_stored_type_outside_the_allowlist_is_not_deserialised(checkpoints: Checkpoints) -> None:
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"held": Unlisted(secret="x")}

    async def write() -> None:
        async with checkpoints.open() as saver:
            await saver.aput(a_config("feature/1"), checkpoint, {"source": "input", "step": 0}, {})

    async def read() -> Any:
        async with checkpoints.open() as saver:
            return await saver.aget_tuple(a_config("feature/1"))

    asyncio.run(write())
    loaded = asyncio.run(read())

    assert loaded is not None
    assert not isinstance(loaded.checkpoint["channel_values"].get("held"), Unlisted)


def test_the_local_saver_opens_the_installations_unit_graphs_file(
    checkpoints: Checkpoints, local_installation: Installation
) -> None:
    async def run() -> None:
        async with checkpoints.open() as saver:
            await saver.aput(a_config("feature/1"), empty_checkpoint(), {}, {})

    asyncio.run(run())

    async def read_directly() -> Any:
        async with open_checkpointer(unit_graphs_path(local_installation.local_dir)) as saver:
            return await saver.aget_tuple(a_config("feature/1"))

    assert asyncio.run(read_directly()) is not None


def test_an_older_database_in_the_state_directory_is_carried_over_once(
    checkpoints: Checkpoints, local_installation: Installation
) -> None:
    old = unit_graphs_path(local_installation.state_dir)

    async def write_old() -> None:
        async with open_checkpointer(old) as saver:
            await saver.aput(a_config("unit-1"), empty_checkpoint(), {}, {})

    async def threads() -> set[str]:
        async with checkpoints.open() as saver:
            return {c.config["configurable"]["thread_id"] async for c in saver.alist(None)}

    asyncio.run(write_old())
    assert asyncio.run(threads()) == {"unit-1"}

    async def write_old_again() -> None:
        async with open_checkpointer(old) as saver:
            await saver.aput(a_config("unit-2"), empty_checkpoint(), {}, {})

    asyncio.run(write_old_again())
    assert asyncio.run(threads()) == {"unit-1"}


def test_a_thread_checkpointed_by_the_saver_before_the_interface_resumes(
    checkpoints: Checkpoints, local_installation: Installation
) -> None:
    state = populated(UnitRun)

    async def before() -> None:
        async with open_checkpointer(unit_graphs_path(local_installation.local_dir)) as saver:
            await run_thread(compile_graph(saver), state, "feature/1")

    async def after() -> Any:
        async with checkpoints.open() as saver:
            return await compile_graph(saver).aget_state(a_config("feature/1"))

    asyncio.run(before())
    snapshot = asyncio.run(after())

    assert UnitRun.model_validate(snapshot.values) == state


class RecordingCheckpoints:
    """A Checkpoints implementation that opens the local saver and counts the openings."""

    opened = 0

    def __init__(self, installation: Installation) -> None:
        self.local = LocalCheckpoints(installation)

    def open(self) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
        RecordingCheckpoints.opened += 1
        return self.local.open()


def test_a_units_thread_is_opened_through_the_registered_implementation(
    local_installation: Installation,
) -> None:
    orchestration.names(INTERFACE)  # load the built-ins, so the registration below is the last
    orchestration.register(INTERFACE, "local", RecordingCheckpoints)
    RecordingCheckpoints.opened = 0

    thread_of(local_installation, "unit-1")

    assert RecordingCheckpoints.opened == 1


@pytest.mark.integration
def test_only_the_local_implementation_names_the_sqlite_opener() -> None:
    allowed = {"graph/checkpointer.py", "orchestration/local/checkpoints.py"}
    offenders = [
        path.relative_to(root).as_posix()
        for root, folder in zip(source_trees(), source_tree_folders(), strict=True)
        for path in guarded_files(under=[folder], suffixes={".py"})
        if path.relative_to(root).as_posix() not in allowed
        and "open_unit_graphs" in path.read_text()
    ]

    assert offenders == [], (
        "these modules open a unit's thread without the Checkpoints interface: "
        + ", ".join(offenders)
    )


POSTGRES_URL = "postgresql+asyncpg://user:secret@db.example:5432/units"


class SaverFactories:
    """Fake saver factories that record which one was opened and with what."""

    def __init__(self) -> None:
        self.opened: list[tuple[str, object]] = []
        self.sqlite_saver = InMemorySaver()
        self.postgres_saver = InMemorySaver()

    @asynccontextmanager
    async def sqlite(self, installation: Installation) -> AsyncIterator[BaseCheckpointSaver]:
        self.opened.append(("sqlite", installation))
        yield self.sqlite_saver

    @asynccontextmanager
    async def postgres(self, url: str) -> AsyncIterator[BaseCheckpointSaver]:
        self.opened.append(("postgres", url))
        yield self.postgres_saver


async def opened_saver(installation: Installation, fakes: SaverFactories) -> BaseCheckpointSaver:
    checkpoints = LocalCheckpoints(installation, sqlite=fakes.sqlite, postgres=fakes.postgres)
    async with checkpoints.open() as saver:
        return saver


def test_a_store_url_selects_the_postgres_saver_over_that_url(tmp_path: Path) -> None:
    installation = make_installation(tmp_path / "planning", store={"url": POSTGRES_URL})
    fakes = SaverFactories()

    saver = asyncio.run(opened_saver(installation, fakes))

    assert saver is fakes.postgres_saver
    assert fakes.opened == [("postgres", POSTGRES_URL)]


def test_a_store_made_of_host_and_database_parts_selects_the_postgres_saver_over_the_built_url(
    tmp_path: Path,
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        store={"host": "db.example", "user": "user", "password": "secret", "database": "units"},
    )
    fakes = SaverFactories()

    saver = asyncio.run(opened_saver(installation, fakes))

    assert saver is fakes.postgres_saver
    assert fakes.opened == [("postgres", POSTGRES_URL)]


@pytest.mark.parametrize(
    "given, expected",
    [
        ("postgresql+asyncpg://u:p%40ss@h:5432/d", "postgresql://u:p%40ss@h:5432/d"),
        ("postgresql://u:p%40ss@h:5432/d", "postgresql://u:p%40ss@h:5432/d"),
    ],
)
def test_the_psycopg_url_is_the_store_url_without_its_driver(given: str, expected: str) -> None:
    assert psycopg_url(given) == expected


def test_no_store_url_selects_the_sqlite_saver(tmp_path: Path) -> None:
    installation = make_installation(tmp_path / "planning")
    fakes = SaverFactories()

    saver = asyncio.run(opened_saver(installation, fakes))

    assert saver is fakes.sqlite_saver
    assert fakes.opened == [("sqlite", installation)]
