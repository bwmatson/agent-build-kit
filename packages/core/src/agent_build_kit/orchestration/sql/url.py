"""The one builder of the units store's database URL."""

from __future__ import annotations

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from agent_build_kit.config import StoreConfig

DRIVER = "postgresql+asyncpg"


def store_url(store: StoreConfig) -> str | None:
    """The URL the store connects with: `store.url` as given, else a `postgresql+asyncpg` URL
    from the five parts with the password escaped; None when neither is set."""
    if store.url:
        return store.url
    if not (store.host and store.database):
        return None
    built = URL.create(
        DRIVER,
        username=store.user,
        password=store.password,
        host=store.host,
        port=store.port,
        database=store.database,
    )
    return built.render_as_string(hide_password=False)


UNPARSEABLE = "<store.url does not parse>"


def parses(url: str) -> bool:
    """Whether `url` is a database URL at all."""
    try:
        make_url(url)
    except ArgumentError:
        return False
    return True


def redacted(url: str) -> str:
    """`url` with its password hidden, for any text a person or a log sees; `UNPARSEABLE` for a
    string that is not a URL, which is never echoed since it may hold the password."""
    if not parses(url):
        return UNPARSEABLE
    return make_url(url).render_as_string(hide_password=True)


def password_of(url: str) -> str | None:
    """The password inside `url`, unescaped; None for a string that is not a URL."""
    return make_url(url).password if parses(url) else None


def missing_parts(store: StoreConfig) -> list[str]:
    """The parts a store needs and lacks: none when `store.url` is set or no part is, else
    `host` and `database` as far as they are unset."""
    if store.url or not any((store.host, store.user, store.password, store.database)):
        return []
    return [name for name in ("host", "database") if not getattr(store, name)]


def escaped(password: str) -> str:
    """`password` as it is written inside a URL."""
    rendered = URL.create("x", username="u", password=password).render_as_string(
        hide_password=False
    )
    return rendered.split(":", 2)[2].removesuffix("@")
