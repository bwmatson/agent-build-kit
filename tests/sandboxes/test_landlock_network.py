"""The Landlock backend's coverage follows the ABI: the TCP rule needs ABI 4 or later."""

from __future__ import annotations

import pytest

from agent_build_kit.sandboxes import Coverage, landlock
from tests.sandboxes.landlock_support import require_working


@pytest.mark.parametrize("abi", [4, 5, 7])
def test_an_abi_with_the_tcp_rule_reaches_process_coverage(
    monkeypatch: pytest.MonkeyPatch, abi: int
) -> None:
    require_working(landlock.BACKEND)
    monkeypatch.setattr(landlock, "abi_version", lambda: abi)

    found = landlock.BACKEND.availability()

    assert found.ok
    assert found.coverage == Coverage.PROCESS


@pytest.mark.parametrize("abi", [1, 2, 3])
def test_an_older_abi_reaches_files_and_says_the_network_is_not_confined(
    monkeypatch: pytest.MonkeyPatch, abi: int
) -> None:
    require_working(landlock.BACKEND)
    monkeypatch.setattr(landlock, "abi_version", lambda: abi)

    found = landlock.BACKEND.availability()

    assert found.ok
    assert found.coverage == Coverage.FILES
    assert "network" in found.cause.lower()
