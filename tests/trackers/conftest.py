"""Fixtures for the tracker tests: the forge's REST environment (a configured PAT and no
subprocess) serves the work item calls too, as they share its credential."""

from __future__ import annotations

import pytest

from agent_build_kit import forges
from agent_build_kit.trackers import start_decision
from tests.forges.conftest import rest_env  # noqa: F401
from tests.forges.stand_in import StandInForge, lookup


@pytest.fixture(autouse=True)
def nobody_else_has_started(monkeypatch: pytest.MonkeyPatch) -> None:
    """A start decision that is not given a forge and a remote asks a host with no pull requests
    and a remote with no branches, so no test reaches a real one."""
    monkeypatch.setattr(forges, "for_repo", lookup(StandInForge()))
    monkeypatch.setattr(start_decision, "remote_head", lambda repo, branch: "")
