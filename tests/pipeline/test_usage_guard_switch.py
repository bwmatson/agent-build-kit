"""With `ABK_USAGE_GUARD=off` a start decision goes ahead without a reading (spec: usage-pause).

The reading is a fake that counts its calls; the endpoint and the home directory are faked
(`tests/usage_host.py`) for the case that needs the guard's own estimate.
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.pipeline.usage_guard import UsageReading, decide_start
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, append_record
from agent_build_kit.settings import settings
from tests.usage_allowance_records import spend
from tests.usage_host import Host, configure, pause_at, payload, refused

MINUTE = timedelta(minutes=1)


class Reads:
    """A reading function that counts the times it was asked."""

    def __init__(self, reading: UsageReading | None) -> None:
        self.reading = reading
        self.calls = 0

    def __call__(self) -> UsageReading | None:
        self.calls += 1
        return self.reading


def reading(
    *, session: int = 91, age: timedelta = timedelta(0), source: str = "live"
) -> UsageReading:
    return UsageReading(
        session_pct=session,
        weekly_pct=10,
        resets_at=datetime.now(UTC) + timedelta(hours=2),
        observed_at=datetime.now(UTC) - age,
        source=source,
        credits_enabled=True,
        credits_used_dollars=0.0,
        spend_limit_reached=False,
    )


@pytest.fixture(autouse=True)
def seventy(host: Host) -> None:
    """A threshold of seventy on both windows, which does not ramp."""
    configure(**pause_at(70))


def guard(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(settings, "usage_guard", value)


def test_a_reading_of_91_against_70_holds_a_start_unset_or_on_and_not_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for value in (None, "on"):
        if value is not None:
            guard(monkeypatch, value)
        reads = Reads(reading())

        decision = decide_start(read=reads)

        assert not decision.may_start
        assert "91" in decision.reason
        assert "70" in decision.reason
        assert reads.calls == 1
    guard(monkeypatch, "off")
    reads = Reads(reading())

    decision = decide_start(read=reads)

    assert decision.may_start
    assert reads.calls == 0


def test_off_an_unreadable_reading_does_not_stop_a_start(monkeypatch: pytest.MonkeyPatch) -> None:
    guard(monkeypatch, "off")
    reads = Reads(None)

    assert decide_start(read=reads).may_start
    assert reads.calls == 0


def test_off_a_stale_reading_over_the_threshold_does_not_stop_a_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard(monkeypatch, "off")
    reads = Reads(reading(age=timedelta(hours=3), source="cache"))

    assert decide_start(read=reads).may_start
    assert reads.calls == 0


def test_off_an_exhausted_allowance_does_not_stop_a_start_and_no_endpoint_call_is_made(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(session={"usage_pause_pct": 92}, weekly={"usage_pause_pct": 80})
    host.keep_reading(89 * MINUTE, payload(session=0.0, weekly=70.0))
    refused(host, cooling=3 * MINUTE)
    for index in range(10):
        record = spend(f"add-marker/{index}", datetime.now(UTC) - 10 * MINUTE)
        append_record(host.cache.parent / LEDGER_NAME, record)
    assert not decide_start().may_start, "on, the estimate is over the threshold"
    guard(monkeypatch, "off")

    assert decide_start().may_start
    assert host.asked == 0
