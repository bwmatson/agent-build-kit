"""A tracker wrapper is not a forge wrapper, and the forge registry can tell them apart."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit import forges
from agent_build_kit.forges.resilient import ResilientForge, RetryPolicy
from agent_build_kit.trackers.local import LocalTracker
from agent_build_kit.trackers.resilient import ResilientTracker
from tests.fake_clock import FakeClock, Waits


def tracker_layer() -> Any:
    waits = Waits(FakeClock())
    return ResilientTracker(
        LocalTracker(), RetryPolicy(attempts=2, deadline_seconds=10.0), waits.clock, waits
    )


def test_a_tracker_wrapper_is_not_a_forge_wrapper() -> None:
    assert not issubclass(ResilientTracker, ResilientForge)
    assert not isinstance(tracker_layer(), ResilientForge)


def test_the_registry_wraps_what_is_not_a_forge_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapped: list[object] = []
    monkeypatch.setattr(forges, "_REGISTRY", {})
    monkeypatch.setattr(forges, "_resilient", lambda forge: wrapped.append(forge) or forge)

    class Named(LocalTracker):
        name = "stand-in"

    waits = Waits(FakeClock())
    tracker = ResilientTracker(
        Named(), RetryPolicy(attempts=2, deadline_seconds=10.0), waits.clock, waits
    )
    forges.register(tracker)  # type: ignore[arg-type]

    assert wrapped == [tracker]
