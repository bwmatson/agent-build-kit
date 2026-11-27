"""A schema of its own in the PostgreSQL database the `azurite` cases run against (the CI job's
PostgreSQL service): the one place that reads the setting, skips without it, and creates and drops
the schema."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import NamedTuple

import pytest

# The connection string of a PostgreSQL database; the `azurite` cases skip without it.
POSTGRES_SETTING = "ABK_TEST_POSTGRES_CONNECTION_STRING"


class PostgresSchema(NamedTuple):
    dsn: str
    name: str

    @property
    def options(self) -> str:
        """The connection option that puts a connection's search path in the schema."""
        return f"-c search_path={self.name}"


@pytest.fixture
def postgres_schema() -> Iterator[PostgresSchema]:
    """A fresh schema in the database named by the setting, dropped after the test."""
    dsn = os.environ.get(POSTGRES_SETTING)
    if not dsn:
        pytest.skip(f"{POSTGRES_SETTING} is not set: no PostgreSQL database to run against")
    psycopg = pytest.importorskip("psycopg")
    schema = PostgresSchema(dsn, f"checkpoints_{uuid.uuid4().hex}")
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema.name}")
        try:
            yield schema
        finally:
            admin.execute(f"DROP SCHEMA {schema.name} CASCADE")
