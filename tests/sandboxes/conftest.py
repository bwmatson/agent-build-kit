"""Fixtures for the sandbox tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.sandboxes import SandboxBackend
from tests.sandboxes.landlock_support import BACKENDS, Scene, require_working


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest) -> Iterator[SandboxBackend]:
    """Each real backend in turn, skipped with its own cause where it cannot be applied."""
    found = sandboxes.get(request.param)
    require_working(found)
    yield found


@pytest.fixture
def registry() -> Iterator[None]:
    """A registry holding only the built-in backends (`landlock`, `unavailable`); what a test
    registers is gone after."""
    with sandboxes.isolated():
        yield


@pytest.fixture
def scene(tmp_path: Path) -> Scene:
    return Scene(tmp_path)
