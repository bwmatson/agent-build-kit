"""The retryable-collector telemetry test gives the same result however loaded the host is.

A loaded host stretches every wall-clock reading. This replays the test with a
clock that reads a long stall between any two calls, so what a slow machine does
at random happens every time, and the test is judged on what the caller sees
(its work done, nothing failed) rather than on how long the host took.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from tests import test_telemetry
from tests.test_telemetry import Receiver, configure  # noqa: F401  (a fixture)

STALL = 60.0


class StalledClock:
    """A monotonic clock that jumps STALL seconds each time it is read."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        self.now += STALL
        return self.now


@pytest.mark.parametrize("status", [503, 429])
def test_the_retryable_collector_test_does_not_depend_on_how_long_the_host_took(
    configure: Callable[..., None],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    monkeypatch.setattr(test_telemetry, "time", SimpleNamespace(monotonic=StalledClock().monotonic))
    receivers = test_telemetry.serve(status)
    receiver: Receiver = next(receivers)
    try:
        with caplog.at_level(logging.DEBUG):
            test_telemetry.test_a_collector_answering_with_a_retryable_error_neither_delays_nor_fails_the_caller(
                configure, receiver, caplog
            )
    finally:
        next(receivers, None)
