"""The retry layer over a tracker: what is repeated, how it waits, and why a claim is not.

The inner tracker is the stand-in behind a proxy that fails a method as scripted, either before
it does anything or after it has done it (an answer lost on the way back)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agent_build_kit.forges.resilient import RetryPolicy
from agent_build_kit.forges.transport import HostError, RateLimited
from agent_build_kit.trackers.local import LocalTracker
from agent_build_kit.trackers.resilient import ResilientTracker
from tests.fake_clock import FakeClock, Waits


class Flaky:
    """Fails the named methods with the next scripted error. `lost` names the methods whose
    effect still happens before the error is raised."""

    def __init__(
        self,
        inner: LocalTracker,
        script: dict[str, list[Exception]],
        lost: frozenset[str] = frozenset(),
    ) -> None:
        self.inner = inner
        self.script = script
        self.lost = lost
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., Any]:
        real = getattr(self.inner, name)

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            pending = self.script.get(name, [])
            if not pending:
                return real(*args, **kwargs)
            error = pending.pop(0)
            if name in self.lost:
                real(*args, **kwargs)
            raise error

        return call

    def made(self, name: str) -> int:
        return self.calls.count(name)


@pytest.fixture
def waits() -> Waits:
    return Waits(FakeClock())


def layer(inner: Flaky, waits: Waits) -> Any:
    return ResilientTracker(
        inner,  # type: ignore[arg-type]
        RetryPolicy(attempts=4, deadline_seconds=1000.0),
        waits.clock,
        waits,
    )


def down() -> HostError:
    return HostError("GET /x: host answered 503")


def test_a_read_is_retried_through_a_transient_error(waits: Waits) -> None:
    store = LocalTracker()
    item = store.create("story", "Story")
    inner = Flaky(store, {"get": [down()]})

    assert layer(inner, waits).get(item.id) == item

    assert inner.made("get") == 2
    assert len(waits.slept) == 1


def test_an_idempotent_write_is_retried_through_a_transient_error(waits: Waits) -> None:
    store = LocalTracker()
    item = store.create("story", "Story")
    inner = Flaky(store, {"update": [down()]})

    updated = layer(inner, waits).update(item.id, {"title": "New"})

    assert updated.title == "New"
    assert inner.made("update") == 2


def test_a_rate_limit_waits_as_the_forge_wrapper_does(waits: Waits) -> None:
    store = LocalTracker()
    item = store.create("story", "Story")
    inner = Flaky(store, {"get": [RateLimited("GET /x: rate limited", retry_after=9)]})

    assert layer(inner, waits).get(item.id) == item

    assert waits.slept == [9]


def test_a_network_failure_is_retried(waits: Waits) -> None:
    store = LocalTracker()
    item = store.create("story", "Story")
    timeout = HostError(f"GET /x: {httpx.ReadTimeout('timed out')!r}")
    inner = Flaky(store, {"children": [timeout, timeout]})

    assert layer(inner, waits).children(item.id) == []

    assert inner.made("children") == 3


def test_a_create_after_a_timeout_looks_for_the_marker_and_does_not_create_twice(
    waits: Waits,
) -> None:
    store = LocalTracker()
    feature = store.create("feature", "Feature")
    inner = Flaky(store, {"create": [down()]}, lost=frozenset({"create"}))

    created = layer(inner, waits).create(
        "story", "Story", parent=feature.id, markers=("abk:story-1",)
    )

    assert inner.made("create") == 1
    assert inner.made("find_by_marker") == 1
    assert created.title == "Story"
    assert [item.id for item in store.children(feature.id)] == [created.id]


def test_a_create_that_did_not_land_is_made_again_once_the_marker_is_not_found(
    waits: Waits,
) -> None:
    store = LocalTracker()
    feature = store.create("feature", "Feature")
    inner = Flaky(store, {"create": [down()]})

    created = layer(inner, waits).create(
        "story", "Story", parent=feature.id, markers=("abk:story-1",)
    )

    assert inner.made("create") == 2
    assert [item.id for item in store.children(feature.id)] == [created.id]


def test_a_claim_is_called_once_and_its_error_returned(waits: Waits) -> None:
    store = LocalTracker()
    item = store.create("story", "Story")
    failure = down()
    inner = Flaky(store, {"claim": [failure]})

    with pytest.raises(HostError) as caught:
        layer(inner, waits).claim(item.id)

    assert caught.value is failure
    assert inner.made("claim") == 1
    assert waits.slept == []


def test_a_claim_that_works_is_passed_through(waits: Waits) -> None:
    store = LocalTracker()
    item = store.create("story", "Story")
    inner = Flaky(store, {})

    assert layer(inner, waits).claim(item.id) is True

    assert inner.made("claim") == 1
    assert store.get(item.id).assignees == (store.identity().name,)
