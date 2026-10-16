"""A provider's month and Claude Code's windows are judged by one ramp, and only the ramp."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_guard import (
    Band,
    Limits,
    UsageReading,
    Window,
    may_start_unit,
    provider_decision,
    threshold_at,
)
from tests.provider_gate_support import limits, reading
from tests.provider_summaries import END, START

MIDWAY = START + timedelta(days=10)


def claude_reading(used: int) -> UsageReading:
    now = datetime.now(UTC)
    return UsageReading(
        session_pct=used,
        weekly_pct=used,
        resets_at=now + timedelta(hours=3),
        weekly_resets_at=now + timedelta(days=3),
        observed_at=now,
        source="live",
        credits_enabled=False,
        credits_used_dollars=0.0,
        spend_limit_reached=False,
    )


def test_a_patched_threshold_at_changes_the_provider_result_and_the_claude_result_alike(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_provider = provider_decision(reading(40), limits=limits(), now=MIDWAY)
    before_claude = may_start_unit(claude_reading(40))
    assert (before_provider.state, before_claude.may_start) == ("usable", True)

    monkeypatch.setattr(usage_guard, "threshold_at", lambda *args, **kwargs: 10)

    after_provider = provider_decision(reading(40), limits=limits(), now=MIDWAY)
    after_claude = may_start_unit(claude_reading(40))

    assert (after_provider.state, after_provider.threshold) == ("held", 10)
    assert after_claude.may_start is False


def test_a_window_may_carry_a_provider_window_name() -> None:
    month = Window(name="billing", used_pct=87, resets_at=END, length=END - START)
    band = Band(pause_pct=70, ceiling_pct=90)

    shared = threshold_at(month, now=MIDWAY, limits=Limits(session=band, weekly=band))

    assert provider_decision(reading(87), limits=limits(), now=MIDWAY).threshold == shared == 70


def test_no_allowance_estimate_or_credit_rule_is_applied_to_a_provider_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(*args: object, **kwargs: object) -> object:
        raise AssertionError("a provider reading is judged as read")

    for name in ("allowance_for", "estimate_usage", "read_allowances", "_decide_on_estimate"):
        monkeypatch.setattr(usage_guard, name, refused)

    result = provider_decision(reading(87), limits=limits(), now=MIDWAY)

    assert (result.state, result.used_pct) == ("held", 87)


def test_a_patched_relief_at_changes_a_standing_provider_hold_and_the_claude_resume_alike(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standing = provider_decision(reading(80), limits=limits(), now=MIDWAY, standing=True)
    assert standing.state == "held"
    resume = datetime.now(UTC) + timedelta(minutes=7)

    monkeypatch.setattr(usage_guard, "relief_at", lambda *args, **kwargs: MIDWAY)

    lifted = provider_decision(reading(80), limits=limits(), now=MIDWAY, standing=True)
    assert lifted.state == "usable"

    monkeypatch.setattr(usage_guard, "relief_at", lambda *args, **kwargs: resume)
    paused = may_start_unit(claude_reading(95))

    assert (paused.may_start, paused.resume_at) == (False, resume)
