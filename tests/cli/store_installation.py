"""Installations and settings for the tests of the units store's connection (`store.*`)."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.installation import Installation, load_installation
from agent_build_kit.settings import settings

STORE_SETTINGS = ("url", "host", "port", "user", "password", "database")

SELF_REPO = {"repos": {"app": {"path": ".", "slug": "example/app"}}}


@pytest.fixture
def no_store_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ambient environment sets no `ABK_STORE_*` variable; loading restores the settings."""
    for name in STORE_SETTINGS:
        monkeypatch.setattr(settings, f"store_{name}", None)
        monkeypatch.delenv(f"ABK_STORE_{name.upper()}", raising=False)


def loaded(
    root: Path, tracked: dict[str, Any] | None = None, local: dict[str, Any] | None = None
) -> Installation:
    """The installation of `root` whose abk.yaml lists its own repository and whose `store`
    block is `tracked`, with `local` as the `store` block of abk.local.yaml when given."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "abk.yaml").write_text(yaml.safe_dump({**SELF_REPO, "store": tracked or {}}))
    if local is not None:
        (root / "abk.local.yaml").write_text(yaml.safe_dump({"store": local}))
    return load_installation(config_path=root / "abk.yaml")


def unused_port() -> int:
    """A loopback port nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
