"""The shared retry engine, driven through a minimal subclass with its own table and hooks."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_build_kit import telemetry
from agent_build_kit.forges import resilient as forge_resilient
from agent_build_kit.forges.operations import OperationSpec
from agent_build_kit.forges.transport import HostError, HostUnavailable, RateLimited
from agent_build_kit.resilient_base import ResilientBase, RetryPolicy, delegating
from tests.fake_clock import FakeClock, Waits

TABLE = {
    "fetch": OperationSpec(kind="read"),
    "make": OperationSpec(kind="create", lands="find_made"),
    "note": OperationSpec(kind="advisory", neutral="nothing"),
}


class Widgets:
    """The wrapped object: fails a method with the next scripted error, and makes things."""

    colour = "blue"

    def __init__(self, script: dict[str, list[Exception]], lost: bool = False) -> None:
        self.script = script
        # A create whose answer is lost still happens before it raises.
        self.lost = lost
        self.calls: list[str] = []
        self.made: list[str] = []

    def _step(self, name: str) -> None:
        self.calls.append(name)
        pending = self.script.get(name, [])
        if pending:
            raise pending.pop(0)

    def fetch(self, key: str) -> str:
        self._step("fetch")
        return f"value:{key}"

    def make(self, key: str) -> str:
        self.calls.append("make")
        pending = self.script.get("make", [])
        if pending:
            if self.lost:
                self.made.append(key)
            raise pending.pop(0)
        self.made.append(key)
        return key

    def find_made(self, key: str) -> str | None:
        self.calls.append("find_made")
        return key if key in self.made else None

    def note(self, text: str) -> str:
        self._step("note")
        return text


class Widget(ResilientBase[Widgets]):
    _subject = "widget"
    _retries_counter = "abk.widget.retries"

    def _can_ask(self, spec: OperationSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        return spec.lands is not None

    def _landed(self, spec: OperationSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        return getattr(self._inner, str(spec.lands))(args[0])


for _name in TABLE:
    setattr(Widget, _name, delegating(_name))


class Counted:
    def __init__(self) -> None:
        self.lines: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, name: str, value: float = 1, **attributes: Any) -> None:
        self.lines.append((name, attributes))

    def outcomes(self, operation: str) -> list[str]:
        return [
            a["outcome"]
            for n, a in self.lines
            if n == "abk.widget.retries" and a["operation"] == operation
        ]


@pytest.fixture
def waits() -> Waits:
    return Waits(FakeClock())


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> Counted:
    counter = Counted()
    monkeypatch.setattr(telemetry, "count", counter)
    return counter


def layer(inner: Widgets, waits: Waits, *, attempts: int = 4, deadline: float = 1000.0) -> Any:
    return Widget(
        inner,
        RetryPolicy(attempts=attempts, deadline_seconds=deadline),
        waits.clock,
        waits,
        table=TABLE,
    )


def down(hint: float | None = None) -> HostError:
    return HostError("GET /x: host answered 503", retry_after=hint)


def test_a_read_is_retried_through_a_transient_error(waits: Waits, counted: Counted) -> None:
    inner = Widgets({"fetch": [down()]})

    assert layer(inner, waits).fetch("a") == "value:a"
    assert inner.calls == ["fetch", "fetch"]
    assert len(waits.slept) == 1
    assert counted.outcomes("fetch") == ["retried"]


def test_what_is_not_an_operation_is_the_inner_objects_own(waits: Waits) -> None:
    assert layer(Widgets({}), waits).colour == "blue"


def test_a_rate_limit_waits_for_the_hosts_hint(waits: Waits) -> None:
    inner = Widgets({"fetch": [RateLimited("slow down", retry_after=30.0)]})

    assert layer(inner, waits).fetch("a") == "value:a"
    assert waits.slept == [30.0]


def test_a_hint_beyond_the_ceiling_raises_the_error_itself(waits: Waits) -> None:
    error = RateLimited("slow down", retry_after=3600.0)
    inner = Widgets({"fetch": [error]})

    with pytest.raises(RateLimited) as raised:
        layer(inner, waits).fetch("a")

    assert raised.value is error
    assert waits.slept == []


def test_a_create_that_landed_is_found_and_not_repeated(waits: Waits, counted: Counted) -> None:
    inner = Widgets({"make": [down()]}, lost=True)

    assert layer(inner, waits).make("k") == "k"
    assert inner.calls == ["make", "find_made"]
    assert inner.made == ["k"]
    assert counted.outcomes("make") == ["landed"]


def test_a_create_that_did_not_land_is_repeated(waits: Waits) -> None:
    inner = Widgets({"make": [down()]})

    assert layer(inner, waits).make("k") == "k"
    assert inner.calls == ["make", "find_made", "make"]
    assert inner.made == ["k"]


def test_a_rate_limited_create_is_repeated_without_a_look_up(waits: Waits) -> None:
    inner = Widgets({"make": [RateLimited("slow", retry_after=1.0)]})

    assert layer(inner, waits).make("k") == "k"
    assert inner.calls == ["make", "make"]


def test_a_contained_operation_returns_its_neutral_value(
    waits: Waits, counted: Counted, caplog: pytest.LogCaptureFixture
) -> None:
    inner = Widgets({"note": [down(), down(), down()]})

    with caplog.at_level(logging.INFO):
        assert layer(inner, waits, attempts=3).note("hi") == "nothing"

    assert counted.outcomes("note") == ["retried", "retried", "contained"]
    assert "widget note: contained after 3 attempts" in caplog.text


def test_the_attempt_limit_stops_a_read(waits: Waits, counted: Counted) -> None:
    inner = Widgets({"fetch": [down(), down(), down()]})

    with pytest.raises(HostUnavailable):
        layer(inner, waits, attempts=3).fetch("a")

    assert inner.calls == ["fetch"] * 3
    assert counted.outcomes("fetch") == ["retried", "retried", "exhausted"]


def test_the_deadline_stops_a_read(waits: Waits) -> None:
    inner = Widgets({"fetch": [down(hint=10.0), down(hint=10.0)]})

    with pytest.raises(HostUnavailable):
        layer(inner, waits, attempts=10, deadline=15.0).fetch("a")

    assert inner.calls == ["fetch", "fetch"]
    assert waits.slept == [10.0]


def test_the_subject_and_counter_are_the_ones_given(
    waits: Waits, counted: Counted, caplog: pytest.LogCaptureFixture
) -> None:
    inner = Widgets({"fetch": [down()]})

    with caplog.at_level(logging.INFO):
        layer(inner, waits).fetch("a")

    assert "widget fetch: attempt 1 of 4 failed" in caplog.text
    assert {name for name, _ in counted.lines} == {"abk.widget.retries"}


def test_the_forge_module_re_exports_the_policy_and_the_clock() -> None:
    from agent_build_kit import resilient_base

    assert forge_resilient.RetryPolicy is resilient_base.RetryPolicy
    assert forge_resilient.Clock is resilient_base.Clock
