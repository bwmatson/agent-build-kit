"""The one builder of the units store's database URL."""

from __future__ import annotations

from agent_build_kit.config import StoreConfig


def store_url(store: StoreConfig) -> str | None:
    """The URL the store connects with: `store.url` as given, else a `postgresql+asyncpg` URL
    from the five parts with the password escaped; None when neither is set."""
    raise NotImplementedError
