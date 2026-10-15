"""Fixtures shared by the integration tests."""

from __future__ import annotations

import pytest

from tests.openspec_cli import probe


@pytest.fixture(scope="session")
def openspec_cli() -> None:
    """The OpenSpec CLI starts, asked once; a test that runs it requests this."""
    probe()
