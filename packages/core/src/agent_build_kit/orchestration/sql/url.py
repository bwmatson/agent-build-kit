"""The one builder of the units store's database URL."""

from __future__ import annotations

from sqlalchemy.engine import URL, make_url

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


def redacted(url: str) -> str:
    """`url` with its password hidden, for any text a person or a log sees."""
    return make_url(url).render_as_string(hide_password=True)


def password_of(url: str) -> str | None:
    """The password inside `url`, unescaped."""
    return make_url(url).password


def escaped(password: str) -> str:
    """`password` as it is written inside a URL."""
    rendered = URL.create("x", username="u", password=password).render_as_string(
        hide_password=False
    )
    return rendered.split(":", 2)[2].removesuffix("@")
