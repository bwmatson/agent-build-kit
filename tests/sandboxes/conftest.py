"""Fixtures for the sandbox tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agent_build_kit import sandboxes


@pytest.fixture
def registry() -> Iterator[None]:
    """A registry holding only the `unavailable` backend; what a test registers is gone after."""
    with sandboxes.isolated():
        yield
