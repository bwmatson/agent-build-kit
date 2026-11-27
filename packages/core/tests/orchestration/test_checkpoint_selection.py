"""Which checkpoint saver the unit graph uses: the store's PostgreSQL one when `store.url` is
set, the SQLite one otherwise. The saver factories are replaced by fakes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.local.checkpoints import LocalCheckpoints
from tests.conftest import make_installation

ROOT = Path(__file__).resolve().parents[4]
POSTGRES_URL = "postgresql+asyncpg://user:secret@db.example:5432/units"


class Recorder:
    """Fake saver factories that record which one was opened and with what."""

    def __init__(self) -> None:
        self.opened: list[tuple[str, object]] = []
        self.sqlite_saver = InMemorySaver()
        self.postgres_saver = InMemorySaver()

    @asynccontextmanager
    async def sqlite(self, installation: Installation):
        self.opened.append(("sqlite", installation))
        yield self.sqlite_saver

    @asynccontextmanager
    async def postgres(self, url: str):
        self.opened.append(("postgres", url))
        yield self.postgres_saver


async def opened_saver(installation: Installation, fakes: Recorder) -> BaseCheckpointSaver:
    checkpoints = LocalCheckpoints(installation, sqlite=fakes.sqlite, postgres=fakes.postgres)
    async with checkpoints.open() as saver:
        return saver


def test_a_store_url_selects_the_postgres_saver_over_that_url(tmp_path: Path) -> None:
    installation = make_installation(tmp_path / "planning", store={"url": POSTGRES_URL})
    fakes = Recorder()

    saver = asyncio.run(opened_saver(installation, fakes))

    assert saver is fakes.postgres_saver
    assert fakes.opened == [("postgres", POSTGRES_URL)]


def test_no_store_url_selects_the_sqlite_saver(tmp_path: Path) -> None:
    installation = make_installation(tmp_path / "planning")
    fakes = Recorder()

    saver = asyncio.run(opened_saver(installation, fakes))

    assert saver is fakes.sqlite_saver
    assert fakes.opened == [("sqlite", installation)]


def configuration_doc() -> str:
    return (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The body of the `### heading` section, up to the next heading."""
    body = text.split(f"### {heading}\n", 1)[1]
    return body.split("\n### ", 1)[0]


def test_the_store_section_says_state_is_shared_through_the_server_not_a_network_drive() -> None:
    store = section(configuration_doc(), "`store`")

    assert "`store.url`" in store
    assert "`abk db" in store
    assert "network drive" in store.lower()


def test_the_network_drive_section_keeps_its_content_and_points_to_the_store_url() -> None:
    drive = section(configuration_doc(), "Network drive")

    assert "`store.url`" in drive
    assert "`units.json`" in drive
    assert "lock probe" in drive
