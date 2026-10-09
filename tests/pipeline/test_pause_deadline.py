"""A pause never points into the past.

A usage pause is written from a reading, and a reading can be old: its window
may have reset hours ago. The deadline is the later of what the reading says
and now plus the unknown-retry interval, the grace is added once, and a stale
reading pauses for its own short interval instead of borrowing its window.
"""

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.config import CLAUDE_CODE, WorkspaceConfig
from agent_build_kit.pipeline.pause import (
    RESUME_GRACE,
    UNKNOWN_RETRY,
    Pause,
    pause_line,
    pause_until,
)
from agent_build_kit.pipeline.usage_guard import (
    UsageReading,
    may_start_unit,
    read_live_usage,
)

SLACK = timedelta(seconds=30)


def reading(
    *,
    source: str = "live",
    age: timedelta = timedelta(0),
    resets_in: timedelta | None = timedelta(hours=2),
    session_pct: int = 10,
    spend_limit_reached: bool = False,
    credits_enabled: bool = False,
) -> UsageReading:
    now = datetime.now(UTC)
    return UsageReading(
        session_pct=session_pct,
        weekly_pct=10,
        resets_at=None if resets_in is None else now + resets_in,
        weekly_resets_at=now + timedelta(days=3),
        observed_at=now - age,
        source=source,
        credits_enabled=credits_enabled,
        credits_used_dollars=4.0,
        spend_limit_reached=spend_limit_reached,
    )


def configure_stale_retry(minutes: int) -> None:
    config_module.activate(
        WorkspaceConfig.model_validate(
            {"runtimes": {CLAUDE_CODE: {"limits": {"usage_stale_retry_minutes": minutes}}}}
        ),
        None,
    )


# --- the deadline --------------------------------------------------------------


def test_a_reset_in_the_past_waits_the_unknown_retry_interval(tmp_path: Path) -> None:
    before = datetime.now(UTC)

    state = pause_until(
        before - timedelta(hours=5), reason="old reset", marker=tmp_path / "paused.json"
    )

    assert state.until >= before + UNKNOWN_RETRY
    assert state.until <= datetime.now(UTC) + UNKNOWN_RETRY + SLACK


def test_a_reset_in_the_future_gets_the_grace_once(tmp_path: Path) -> None:
    resets_at = datetime.now(UTC) + timedelta(hours=2)

    state = pause_until(resets_at, reason="soon", marker=tmp_path / "paused.json")

    assert state.until == resets_at + RESUME_GRACE


def test_a_reset_that_just_passed_is_unknown(tmp_path: Path) -> None:
    before = datetime.now(UTC)

    state = pause_until(
        before - timedelta(seconds=1), reason="just passed", marker=tmp_path / "paused.json"
    )

    assert state.until >= before + UNKNOWN_RETRY


def test_the_guard_and_the_pause_add_the_grace_once_between_them(tmp_path: Path) -> None:
    state = reading(resets_in=timedelta(hours=2), spend_limit_reached=True)

    decision = may_start_unit(state)
    paused = pause_until(decision.resume_at, reason=decision.reason, marker=tmp_path / "p.json")

    assert state.resets_at is not None
    assert paused.until == state.resets_at + RESUME_GRACE


@pytest.mark.parametrize("branch", ["spend_limit", "credits"])
def test_the_spend_limit_and_credits_never_end_before_now(tmp_path: Path, branch: str) -> None:
    before = datetime.now(UTC)
    state = reading(
        resets_in=-timedelta(hours=3),
        spend_limit_reached=branch == "spend_limit",
        credits_enabled=branch == "credits",
        session_pct=100,
    )

    decision = may_start_unit(state)
    paused = pause_until(decision.resume_at, reason=decision.reason, marker=tmp_path / "p.json")

    assert not decision.may_start
    assert paused.until >= before + UNKNOWN_RETRY


def test_a_threshold_refusal_next_to_a_passed_reset_never_ends_before_now(
    tmp_path: Path,
) -> None:
    before = datetime.now(UTC)

    decision = may_start_unit(reading(session_pct=95, resets_in=-timedelta(hours=1)))
    paused = pause_until(decision.resume_at, reason=decision.reason, marker=tmp_path / "p.json")

    assert not decision.may_start
    assert paused.until >= before + UNKNOWN_RETRY


# --- a stale reading -----------------------------------------------------------


def test_a_stale_reading_refuses_for_five_minutes_by_default() -> None:
    before = datetime.now(UTC)

    decision = may_start_unit(
        reading(source="claude.json", age=timedelta(hours=6), resets_in=-timedelta(hours=1))
    )

    assert not decision.may_start
    assert decision.resume_at is not None
    assert before + timedelta(minutes=5) <= decision.resume_at
    assert decision.resume_at <= datetime.now(UTC) + timedelta(minutes=5) + SLACK


def test_the_stale_retry_interval_is_a_setting() -> None:
    configure_stale_retry(12)
    before = datetime.now(UTC)

    decision = may_start_unit(reading(source="claude.json", age=timedelta(hours=6)))

    assert decision.resume_at is not None
    assert before + timedelta(minutes=12) <= decision.resume_at
    assert decision.resume_at <= datetime.now(UTC) + timedelta(minutes=12) + SLACK


def test_a_stale_reading_does_not_use_its_own_window() -> None:
    """Its reset is two hours out; the pause is still the short interval."""
    decision = may_start_unit(
        reading(source="claude.json", age=timedelta(hours=6), resets_in=timedelta(hours=2))
    )

    assert decision.resume_at is not None
    assert decision.resume_at < datetime.now(UTC) + timedelta(minutes=10)


def test_the_stale_reason_says_it_is_stale_and_names_the_source() -> None:
    decision = may_start_unit(reading(source="claude.json", age=timedelta(hours=6)))

    assert "stale" in decision.reason
    assert "claude.json" in decision.reason


def test_a_reading_from_the_cache_is_not_exempt_from_the_staleness_test() -> None:
    decision = may_start_unit(reading(source="cache", age=timedelta(hours=6)))

    assert not decision.may_start
    assert "stale" in decision.reason
    assert "cache" in decision.reason


def test_a_reading_served_from_the_cache_file_has_a_source_of_its_own(tmp_path: Path) -> None:
    cache = tmp_path / "usage-cache.json"
    fetched_at = datetime.now(UTC) - timedelta(minutes=1)
    cache.write_text(
        json.dumps(
            {
                "five_hour": {
                    "utilization": 14.0,
                    "resets_at": (fetched_at + timedelta(hours=2)).isoformat(),
                },
                "seven_day": {
                    "utilization": 6.0,
                    "resets_at": (fetched_at + timedelta(days=3)).isoformat(),
                },
                "fetched_at": fetched_at.isoformat(),
            }
        )
    )

    def fetch(url: str, headers: dict[str, str]) -> object:
        raise AssertionError("the endpoint should not be called")

    served = read_live_usage(token="t", fetch=fetch, cache_path=cache)

    assert served is not None
    assert served.source == "cache"
    assert not served.is_live


def test_an_answer_the_endpoint_just_gave_is_live(tmp_path: Path) -> None:
    payload = {
        "five_hour": {
            "utilization": 14.0,
            "resets_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        },
        "seven_day": {
            "utilization": 6.0,
            "resets_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        },
    }

    served = read_live_usage(
        token="t", fetch=lambda url, headers: payload, cache_path=tmp_path / "c.json"
    )

    assert served is not None
    assert served.source == "live"


# --- the line ------------------------------------------------------------------


@pytest.fixture
def kolkata(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A zone five and a half hours from UTC, so local and UTC differ."""
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_the_pause_line_shows_local_time_and_the_reason(kolkata: None) -> None:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    state = Pause(until=now + timedelta(hours=1), reason="weekly usage at 92%")

    line = pause_line(state, now=now)

    assert "18:30" in line
    assert "UTC" not in line
    assert "weekly usage at 92%" in line


def test_the_pause_line_is_never_earlier_than_when_it_is_printed(kolkata: None) -> None:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    state = Pause(until=now - timedelta(hours=3), reason="stale")

    line = pause_line(state, now=now)

    assert "17:30" in line
    assert "14:30" not in line
