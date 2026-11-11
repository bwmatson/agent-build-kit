"""The Checkpoints interface: one conformance suite that takes an implementation.

The suite runs here against the local implementation; the local-only cases pin that the saver
opens the installation's unit graphs file, carries an older database over, and resumes a thread
the saver checkpointed before the interface existed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint

from agent_build_kit import orchestration
from agent_build_kit.cli.pipeline import thread_of
from agent_build_kit.graph.build import compile_graph
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.run import run_thread
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.checkpoints import INTERFACE, Checkpoints
from agent_build_kit.orchestration.local.checkpoints import LocalCheckpoints
from tests.conftest import make_installation
from tests.graph.checkpoint_reads import a_config
from tests.graph.test_checkpoint_allowlist import Unlisted, populated
from tests.tracked_files import ROOT, guarded_files


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


@pytest.fixture(params=["local"])
def checkpoints(request: pytest.FixtureRequest, local_installation: Installation) -> Checkpoints:
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
    allowed = {
        "src/agent_build_kit/graph/checkpointer.py",
        "src/agent_build_kit/orchestration/local/checkpoints.py",
    }
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in guarded_files(under=["src/agent_build_kit"], suffixes={".py"})
        if path.relative_to(ROOT).as_posix() not in allowed
        and "open_unit_graphs" in path.read_text()
    ]

    assert offenders == [], (
        "these modules open a unit's thread without the Checkpoints interface: "
        + ", ".join(offenders)
    )
