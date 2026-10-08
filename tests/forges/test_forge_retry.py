"""The retry layer over a fake forge and a fake clock: what is repeated, how long it
waits, and what it raises once it gives up. The fake forge is the protocol boundary:
each operation answers what it is scripted to, in turn, and records its calls."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agent_build_kit import telemetry
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.operations import OPERATIONS, OperationSpec
from agent_build_kit.forges.resilient import ResilientForge, RetryPolicy
from agent_build_kit.forges.transport import (
    MAX_DELAY,
    AuthError,
    HostError,
    HostUnavailable,
    NotFound,
    RateLimited,
    TransportError,
)
from tests.fake_clock import FakeClock

REPO = RepoId(forge="github", account="example", name="app")
ATTEMPTS = 4


class FakeForge:
    """Each operation pops its next scripted outcome: an exception is raised, a
    value returned; the last outcome repeats."""

    def __init__(self, **script: list[Any]) -> None:
        self.script = script
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            outcomes = self.script[name]
            outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return call

    def made(self, name: str) -> int:
        return sum(1 for call in self.calls if call[0] == name)


class Waits:
    """The sleeper: records each wait and moves the fake clock by it."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.slept: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)


class Counted:
    def __init__(self) -> None:
        self.lines: list[tuple[str, dict]] = []

    def __call__(self, name: str, value: float = 1, **attributes: Any) -> None:
        self.lines.append((name, attributes))

    def outcomes(self, operation: str) -> list[str]:
        return [
            a["outcome"]
            for n, a in self.lines
            if n == "abk.forge.retries" and a["operation"] == operation
        ]


@pytest.fixture
def waits() -> Waits:
    return Waits(FakeClock())


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> Counted:
    counter = Counted()
    monkeypatch.setattr(telemetry, "count", counter)
    return counter


def layer(
    inner: FakeForge,
    waits: Waits,
    *,
    attempts: int = ATTEMPTS,
    deadline: float = 1000.0,
    table: Any = OPERATIONS,
) -> Any:
    return ResilientForge(
        inner,  # type: ignore[arg-type]
        RetryPolicy(attempts=attempts, deadline_seconds=deadline),
        waits.clock,
        waits,
        table=table,
    )


def down(status: int = 503, hint: float | None = None) -> HostError:
    return HostError(f"GET /x: host answered {status}", retry_after=hint)


def limited(hint: float | None) -> RateLimited:
    return RateLimited("GET /x: rate limited", retry_after=hint)


def create(forge: Any) -> int:
    return forge.create_pr(REPO, head="h", base="main", title="t", body="b")


# --- reads and idempotent writes ---------------------------------------------------


def test_a_read_repeats_on_a_server_error_then_succeeds(waits: Waits) -> None:
    inner = FakeForge(pr_files=[down(), ["a.py"]])

    assert layer(inner, waits).pr_files(REPO, 7) == ["a.py"]

    assert inner.made("pr_files") == 2
    assert len(waits.slept) == 1


def test_a_read_repeats_on_a_network_failure(waits: Waits) -> None:
    timeout = HostError(f"GET /x: {httpx.ReadTimeout('timed out')!r}")
    inner = FakeForge(pr_files=[timeout, timeout, ["a.py"]])

    assert layer(inner, waits).pr_files(REPO, 7) == ["a.py"]

    assert inner.made("pr_files") == 3


def test_an_idempotent_write_repeats_on_a_server_error(waits: Waits) -> None:
    inner = FakeForge(post_status=[down(), None])

    layer(inner, waits).post_status(REPO, sha="s", ok=True, context="c", description="d")

    assert inner.made("post_status") == 2


def test_a_host_that_stays_down_fails_after_the_bound_with_the_unavailable_error(
    waits: Waits,
) -> None:
    inner = FakeForge(pr_files=[down()])

    with pytest.raises(HostUnavailable) as caught:
        layer(inner, waits).pr_files(REPO, 7)

    assert inner.made("pr_files") == ATTEMPTS
    assert caught.value.operation == "pr_files"
    assert caught.value.attempts == ATTEMPTS
    assert "503" in caught.value.cause
    assert isinstance(caught.value, TransportError)
    assert isinstance(caught.value.__cause__, HostError)


def test_the_backoff_grows_with_jitter_and_stays_under_the_ceiling(waits: Waits) -> None:
    inner = FakeForge(pr_files=[down()])

    with pytest.raises(HostUnavailable):
        layer(inner, waits, attempts=6, deadline=10_000.0).pr_files(REPO, 7)

    assert len(waits.slept) == 5
    for n, seconds in enumerate(waits.slept):
        assert 0.25 * 2**n <= seconds <= min(0.75 * 2**n, MAX_DELAY)


def test_a_rate_limit_waits_the_larger_of_the_backoff_and_its_hint(waits: Waits) -> None:
    inner = FakeForge(pr_files=[limited(9), ["a.py"]])

    assert layer(inner, waits).pr_files(REPO, 7) == ["a.py"]

    assert waits.slept == [9]


def test_a_hint_below_the_backoff_does_not_shorten_it(waits: Waits) -> None:
    inner = FakeForge(pr_files=[down(hint=0.0), down(hint=0.0), ["a.py"]])

    layer(inner, waits).pr_files(REPO, 7)

    assert waits.slept[1] >= 0.25 * 2


def test_a_rate_limit_that_persists_fails_unavailable_after_the_bound(waits: Waits) -> None:
    inner = FakeForge(pr_files=[limited(5)])

    with pytest.raises(HostUnavailable) as caught:
        layer(inner, waits).pr_files(REPO, 7)

    assert inner.made("pr_files") == ATTEMPTS
    assert isinstance(caught.value.__cause__, RateLimited)
    assert all(s >= 5 for s in waits.slept)


@pytest.mark.parametrize("error", [limited(MAX_DELAY + 1), down(hint=MAX_DELAY + 1)])
def test_a_hint_over_the_ceiling_fails_at_once_with_the_hint(
    waits: Waits, error: TransportError
) -> None:
    inner = FakeForge(pr_files=[error])

    with pytest.raises(TransportError) as caught:
        layer(inner, waits).pr_files(REPO, 7)

    assert getattr(caught.value, "retry_after", None) == MAX_DELAY + 1
    assert inner.made("pr_files") == 1
    assert waits.slept == []


def test_the_total_deadline_stops_a_run_of_long_waits(waits: Waits) -> None:
    started = waits.clock.monotonic()
    inner = FakeForge(pr_files=[limited(40)])

    with pytest.raises(HostUnavailable):
        layer(inner, waits, attempts=10, deadline=100.0).pr_files(REPO, 7)

    assert 1 < inner.made("pr_files") < 10
    assert waits.clock.monotonic() - started <= 100.0


# --- creates -----------------------------------------------------------------------


def test_a_create_that_landed_returns_the_read_result_without_a_second_create(
    waits: Waits, counted: Counted
) -> None:
    inner = FakeForge(create_pr=[down()], find_pr=[9])

    assert create(layer(inner, waits)) == 9

    assert inner.made("create_pr") == 1
    assert inner.made("find_pr") == 1
    assert counted.outcomes("create_pr") == ["landed"]


def test_the_declared_read_is_asked_about_the_head_that_was_created(waits: Waits) -> None:
    inner = FakeForge(create_pr=[down()], find_pr=[9])

    create(layer(inner, waits))

    assert inner.calls[-1] == ("find_pr", (REPO,), {"head": "h"})


def test_a_create_that_did_not_land_is_repeated(waits: Waits) -> None:
    inner = FakeForge(create_pr=[down(502), 11], find_pr=[None])

    assert create(layer(inner, waits)) == 11

    assert inner.made("create_pr") == 2
    assert inner.made("find_pr") == 1


def test_a_failing_read_counts_as_an_attempt(waits: Waits) -> None:
    inner = FakeForge(create_pr=[down(), 11], find_pr=[down(), None])

    assert create(layer(inner, waits)) == 11

    assert inner.made("create_pr") == 2
    assert inner.made("find_pr") == 2


def test_a_create_whose_read_keeps_failing_gives_up_at_the_bound(waits: Waits) -> None:
    inner = FakeForge(create_pr=[down()], find_pr=[down()])

    with pytest.raises(HostUnavailable) as caught:
        create(layer(inner, waits))

    assert caught.value.operation == "create_pr"
    assert inner.made("create_pr") + inner.made("find_pr") <= 2 * ATTEMPTS


def test_a_create_is_never_repeated_when_no_read_is_declared(waits: Waits) -> None:
    table = {**OPERATIONS, "create_pr": OperationSpec(kind="create")}
    inner = FakeForge(create_pr=[down(502), 11])

    with pytest.raises(TransportError):
        create(layer(inner, waits, table=table))

    assert inner.made("create_pr") == 1
    assert waits.slept == []


def test_a_rate_limited_create_is_repeated_without_asking_the_read(waits: Waits) -> None:
    """The host refused it before doing anything."""
    inner = FakeForge(create_pr=[limited(3), 9])

    assert create(layer(inner, waits)) == 9

    assert inner.made("create_pr") == 2
    assert inner.made("find_pr") == 0
    assert waits.slept == [3]


# --- advisory calls and permanent errors -------------------------------------------


def test_an_advisory_call_that_cannot_complete_is_contained(
    waits: Waits, counted: Counted, caplog: pytest.LogCaptureFixture
) -> None:
    inner = FakeForge(set_draft=[down()])

    with caplog.at_level(logging.INFO):
        result = layer(inner, waits).set_draft(REPO, 7, True)

    assert result is None
    assert inner.made("set_draft") == ATTEMPTS
    assert counted.outcomes("set_draft")[-1] == "contained"
    assert "set_draft" in caplog.text


def test_an_advisory_call_is_retried_before_it_is_contained(waits: Waits) -> None:
    inner = FakeForge(set_draft=[down(), None])

    layer(inner, waits).set_draft(REPO, 7, True)

    assert inner.made("set_draft") == 2


PERMANENT = [
    AuthError("GET /x: 401"),
    NotFound("GET /x: not found", account="example", source="setting"),
    TransportError("GET /x: 422"),
]


@pytest.mark.parametrize("error", PERMANENT)
def test_a_permanent_error_on_a_read_is_never_retried(waits: Waits, error: TransportError) -> None:
    inner = FakeForge(pr_files=[error])

    with pytest.raises(type(error)):
        layer(inner, waits).pr_files(REPO, 7)

    assert inner.made("pr_files") == 1
    assert waits.slept == []


@pytest.mark.parametrize("error", PERMANENT)
def test_a_permanent_error_on_a_write_is_never_retried(waits: Waits, error: TransportError) -> None:
    inner = FakeForge(post_status=[error])

    with pytest.raises(type(error)):
        layer(inner, waits).post_status(REPO, sha="s", ok=True, context="c", description="d")

    assert inner.made("post_status") == 1
    assert waits.slept == []


@pytest.mark.parametrize("error", PERMANENT)
def test_a_permanent_error_on_an_advisory_call_is_not_retried(
    waits: Waits, error: TransportError
) -> None:
    inner = FakeForge(set_draft=[error])

    try:
        layer(inner, waits).set_draft(REPO, 7, True)
    except TransportError:
        pass

    assert inner.made("set_draft") == 1
    assert waits.slept == []


@pytest.mark.parametrize("error", PERMANENT)
def test_a_permanent_error_on_a_create_is_not_followed_by_the_read(
    waits: Waits, error: TransportError
) -> None:
    inner = FakeForge(create_pr=[error], find_pr=[None])

    with pytest.raises(type(error)):
        create(layer(inner, waits))

    assert inner.made("create_pr") == 1
    assert inner.made("find_pr") == 0


# --- visibility --------------------------------------------------------------------


def test_each_retry_is_logged_with_operation_attempt_and_cause(
    waits: Waits, caplog: pytest.LogCaptureFixture
) -> None:
    inner = FakeForge(pr_files=[down(), down(), ["a.py"]])

    with caplog.at_level(logging.INFO):
        layer(inner, waits).pr_files(REPO, 7)

    lines = [r.getMessage() for r in caplog.records if "forge pr_files" in r.getMessage()]
    assert len(lines) == 2
    assert lines[0].startswith(f"forge pr_files: attempt 1 of {ATTEMPTS} failed (")
    assert "503" in lines[0] and "waiting" in lines[0]
    assert lines[1].startswith(f"forge pr_files: attempt 2 of {ATTEMPTS} failed (")


def test_each_retry_and_the_exhaustion_are_counted_by_operation_and_outcome(
    waits: Waits, counted: Counted
) -> None:
    inner = FakeForge(pr_files=[down()])

    with pytest.raises(HostUnavailable):
        layer(inner, waits).pr_files(REPO, 7)

    assert counted.outcomes("pr_files") == ["retried"] * (ATTEMPTS - 1) + ["exhausted"]
    assert {n for n, _ in counted.lines} == {"abk.forge.retries"}


def test_a_call_that_succeeds_first_time_logs_and_counts_nothing(
    waits: Waits, counted: Counted, caplog: pytest.LogCaptureFixture
) -> None:
    inner = FakeForge(pr_files=[["a.py"]])

    with caplog.at_level(logging.INFO):
        layer(inner, waits).pr_files(REPO, 7)

    assert counted.lines == []
    assert "forge pr_files" not in caplog.text
