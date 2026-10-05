"""`build_resume_at` answers the runner's question of when the usage guard
expects to allow a start again, for the interrupt a refusal makes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_build_kit.pipeline.usage_guard import UsageReading, may_start_unit
from agent_build_kit.pipeline.wiring import build_resume_at


def reading(**overrides) -> UsageReading:
    defaults: dict = {
        "session_pct": 10,
        "weekly_pct": 10,
        "resets_at": datetime.now(UTC) + timedelta(hours=3),
        "observed_at": datetime.now(UTC),
        "source": "live",
        "credits_enabled": True,
        "credits_used_dollars": 0.0,
        "spend_limit_reached": False,
    }
    return UsageReading(**{**defaults, **overrides})


def test_a_refusing_guard_gives_its_own_time_to_ask_again() -> None:
    full = reading(session_pct=99)
    decision = may_start_unit(full)
    assert not decision.may_start
    assert decision.resume_at is not None

    assert build_resume_at(usage=lambda: full)() == decision.resume_at


def test_a_guard_that_has_no_time_of_its_own_gives_the_windows_reset() -> None:
    open_window = reading()

    assert build_resume_at(usage=lambda: open_window)() == open_window.resets_at
