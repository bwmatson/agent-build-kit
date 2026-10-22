"""Fixtures for the sandbox tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from tests.sandboxes.landlock_support import Scene


@pytest.fixture
def registry() -> Iterator[None]:
    """A registry holding only the `unavailable` backend; what a test registers is gone after."""
    with sandboxes.isolated():
        yield


@pytest.fixture
def scene(tmp_path: Path) -> Scene:
    return Scene(tmp_path)
