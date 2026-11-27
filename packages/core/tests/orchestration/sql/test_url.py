"""The one builder of the units store's URL (spec: unit-store, "The connection is five settings
with one builder")."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from agent_build_kit.config import StoreConfig
from agent_build_kit.orchestration.sql.url import (
    UNPARSEABLE,
    missing_parts,
    parses,
    redacted,
    store_url,
)


@pytest.mark.parametrize("password", ["p@ss", "pa/ss", "pa:ss", "a@b/c:d"])
def test_the_builder_makes_an_asyncpg_url_that_parses_back_to_its_parts(password: str) -> None:
    url = store_url(StoreConfig(host="db.example", user="abk", password=password, database="units"))

    parsed = make_url(url or "")
    assert parsed.drivername == "postgresql+asyncpg"
    assert (parsed.host, parsed.port) == ("db.example", 5432)
    assert (parsed.username, parsed.password, parsed.database) == ("abk", password, "units")


def test_a_url_that_is_set_is_used_as_given_beside_the_parts() -> None:
    given = "sqlite+aiosqlite:///given.db"

    store = StoreConfig(url=given, host="db.example", user="abk", password="x", database="units")

    assert store_url(store) == given


def test_the_dialect_the_builder_names_can_be_loaded_without_connecting() -> None:
    url = store_url(StoreConfig(host="db.example", database="units"))

    engine = create_async_engine(url or "")

    assert engine.dialect.driver == "asyncpg"


def test_a_string_that_is_not_a_url_is_described_and_never_echoed() -> None:
    typo = "localhost:5432/units-secret"

    assert not parses(typo)
    assert redacted(typo) == UNPARSEABLE


def test_a_url_is_shown_without_its_password() -> None:
    assert "hunter2" not in redacted("postgresql+asyncpg://abk:hunter2@db.example/units")


@pytest.mark.parametrize(
    ("store", "absent"),
    [
        (StoreConfig(), []),
        (StoreConfig(url="sqlite+aiosqlite:///x.db", user="abk"), []),
        (StoreConfig(host="db.example", database="units"), []),
        (StoreConfig(host="db.example", user="abk", password="x"), ["database"]),
        (StoreConfig(user="abk", database="units"), ["host"]),
        (StoreConfig(user="abk"), ["host", "database"]),
    ],
)
def test_the_parts_a_store_lacks_are_named_only_when_some_part_is_set(
    store: StoreConfig, absent: list[str]
) -> None:
    assert missing_parts(store) == absent
