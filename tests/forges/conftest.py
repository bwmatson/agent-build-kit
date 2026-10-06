"""Fixtures for the Azure DevOps REST tests (`test_azure_rest_*.py`)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest

from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.settings import settings

PAT = "pat-secret"


@pytest.fixture
def rest_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A PAT is configured, and starting any process fails the test: the forge
    reaches Azure DevOps over HTTP and nothing else."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"a subprocess was started: {args[:1]}")

    monkeypatch.setattr(settings, "ado_pat", PAT)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    clear_credentials()
    yield
    clear_credentials()
