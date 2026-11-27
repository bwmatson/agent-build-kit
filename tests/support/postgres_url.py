"""The one place a test reads the PostgreSQL server it may write to.

The server comes from `ABK_TEST_STORE_HOST`, `_PORT`, `_USER`, `_PASSWORD` and `_DATABASE`, named
as the store's own settings with `TEST_` added. A host, port, user or password that is missing or
blank falls back to the store's own setting of the same name without `TEST_`; the database never
does, so a test cannot reach the real store's database by leaving it out. The URL is made by the
store's one URL builder, and a server, port and database that are the real store's own are refused.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from sqlalchemy.engine import make_url

from agent_build_kit.config import StoreConfig
from agent_build_kit.orchestration.sql.url import store_url

PARTS = ("host", "port", "user", "password", "database")
# The parts a test cannot go without; a password may be empty on a server that trusts the client.
REQUIRED = ("host", "user", "database")
# The parts that fall back to the store's own setting.
FALLS_BACK = ("host", "port", "user", "password")


class TestStoreNotConfigured(RuntimeError):
    """A required test-store variable is missing."""

    __test__ = False


class TestStoreIsTheRealStore(RuntimeError):
    """The test variables name the store's own server, port and database."""

    __test__ = False


def _value(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name, "").strip()
    return value or None


def _own(environ: Mapping[str, str]) -> StoreConfig:
    """The real store's connection as the environment gives it (`ABK_STORE_URL` or the parts)."""
    url = _value(environ, "ABK_STORE_URL")
    if url:
        parsed = make_url(url)
        return StoreConfig(host=parsed.host, port=parsed.port or 5432, database=parsed.database)
    port = _value(environ, "ABK_STORE_PORT")
    return StoreConfig(
        host=_value(environ, "ABK_STORE_HOST"),
        port=int(port) if port else 5432,
        database=_value(environ, "ABK_STORE_DATABASE"),
    )


def postgres_url(environ: Mapping[str, str] | None = None) -> str:
    """The URL of the test PostgreSQL database, from `environ` (the process environment)."""
    env = os.environ if environ is None else environ
    found: dict[str, str | None] = {}
    for part in PARTS:
        found[part] = _value(env, f"ABK_TEST_STORE_{part.upper()}")
        if found[part] is None and part in FALLS_BACK:
            found[part] = _value(env, f"ABK_STORE_{part.upper()}")
    for part in REQUIRED:
        if found[part] is None:
            fallback = (
                f" (or the store's own ABK_STORE_{part.upper()})" if part in FALLS_BACK else ""
            )
            raise TestStoreNotConfigured(
                f"ABK_TEST_STORE_{part.upper()} is not set{fallback}: add it to verify.env and "
                ".env as the manual step test-store-env says"
            )
    port = found["port"]
    test = StoreConfig(
        host=found["host"],
        port=int(port) if port else 5432,
        user=found["user"],
        password=found["password"],
        database=found["database"],
    )
    own = _own(env)
    if (test.host, test.port, test.database) == (own.host, own.port, own.database):
        raise TestStoreIsTheRealStore(
            f"the test store {test.host}:{test.port}/{test.database} is the store's own; "
            "ABK_TEST_STORE_DATABASE must name another database"
        )
    url = store_url(test)
    assert url is not None
    return url
