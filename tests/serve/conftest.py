from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import start_server
from tests.conftest import make_installation


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return installation


@pytest.fixture
def api(inst: Installation) -> Iterator[httpx.Client]:
    """A client of a server running over `inst`."""
    with start_server(inst) as server, httpx.Client(base_url=server.url) as client:
        yield client


@pytest.fixture
def new_york_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The host clock at UTC-5 all year, so a log's local stamps differ from UTC."""
    monkeypatch.setenv("TZ", "EST5")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()
